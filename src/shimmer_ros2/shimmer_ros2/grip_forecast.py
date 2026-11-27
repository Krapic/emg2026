"""Forecast grip force a fraction of a second ahead from its own recent history.

Hankel dynamic mode decomposition: the last second of the force estimate is
stacked into delayed copies, a linear map that advances them by one sample is
fitted, and its eigenvalues extrapolate the signal. Follows the prediction step
of Bazina et al., "Koopman-driven Grip Force Prediction Through EMG Sensing"
(arXiv:2409.17340), without its smoothing, logarithmic observables and refined
mode selection. Uses only NumPy.
"""

import numpy as np

from shimmer_ros2.grip_data import NS

# Chosen on the two bundled recordings that contain gripping; revisit them once
# recordings that follow the protocol exist.
FORECAST_HZ = 40.0
WINDOW_SEC = 1.0
DELAYS = 4
MODES = 4
# The history must not bridge an outage of the estimate.
MAX_GAP_NS = 50_000_000
HORIZONS_MS = (100, 250, 500)
PERIOD_NS = round(NS / FORECAST_HZ)
WINDOW_SAMPLES = round(WINDOW_SEC * FORECAST_HZ)


def hankel_dmd(series, steps, delays=DELAYS, modes=MODES):
    """Extrapolate a uniformly sampled series `steps` samples past its end.

    `steps` may hold fractions of a sample. The forecast continues from the
    last sample, so a zero step returns it unchanged.
    """
    series = np.asarray(series, dtype=float)
    steps = np.asarray(steps, dtype=float)
    scale = np.abs(series).max()
    count = len(series) - delays + 1
    if count < 2:
        raise ValueError('Povijest je kraća od broja odgoda.')
    if scale == 0:
        return np.zeros(len(steps))
    hankel = np.stack([series[row:row + count] for row in range(delays)]) / scale
    before, after = hankel[:, :-1], hankel[:, 1:]
    left, singular, right = np.linalg.svd(before, full_matrices=False)
    rank = min(modes, int(np.sum(singular > 1e-8 * singular[0])))
    if rank == 0:
        return np.full(len(steps), series[-1])
    left, singular, right = left[:, :rank], singular[:rank], right[:rank]
    eigenvalues, vectors = np.linalg.eig(left.T @ after @ right.T / singular)
    eigenvalues = eigenvalues.astype(complex)
    shapes = left @ vectors
    # A growing mode fits a rise inside the window but runs away beyond it.
    radius = np.abs(eigenvalues)
    eigenvalues = np.where(radius > 1, eigenvalues / radius, eigenvalues)
    # One amplitude per mode, fitted to every snapshot of the window.
    powers = eigenvalues[None, :] ** np.arange(count)[:, None]
    design = (powers[:, None, :] * shapes[None, :, :]).reshape(count * delays, rank)
    amplitudes, *_ = np.linalg.lstsq(design, hankel.T.reshape(-1).astype(complex), rcond=None)
    newest = shapes[-1] * amplitudes * powers[-1]
    change = ((eigenvalues[None, :] ** steps[:, None] - 1) * newest).sum(axis=1).real
    # Forecasting the change keeps the fit error at the last sample out of the result.
    return series[-1] + scale * change


def recent_history(stamps, values):
    """Resample the last window onto the forecast grid; None when it is not covered."""
    stamps = np.asarray(stamps, dtype=np.int64)
    values = np.asarray(values, dtype=float)
    if len(stamps) < 2:
        return None
    start = stamps[-1] - (WINDOW_SAMPLES - 1) * PERIOD_NS
    first = np.searchsorted(stamps, start, side='right') - 1
    if first < 0 or np.diff(stamps[first:]).max() > MAX_GAP_NS:
        return None
    seconds = (stamps[first:] - stamps[-1]) / NS
    grid = -np.arange(WINDOW_SAMPLES - 1, -1, -1) / FORECAST_HZ
    history = np.interp(grid, seconds, values[first:])
    return history if np.isfinite(history).all() else None


def forecast(stamps, values, horizons_ns, bounds=None):
    """Forecast the series at each horizon past its last stamp; None without enough history.

    `bounds` is the (lowest, highest) force the result may take, usually the
    range seen in training.
    """
    history = recent_history(stamps, values)
    if history is None:
        return None
    result = hankel_dmd(history, np.asarray(horizons_ns, dtype=float) / PERIOD_NS)
    return result if bounds is None else np.clip(result, *bounds)


def compare(times, signal, truth, horizons_ms=HORIZONS_MS, issue_ns=50_000_000):
    """Score forecasts of `signal` against `truth` and against holding the last value.

    A forecast is issued every `issue_ns` from the samples up to that moment.
    Forecasts are not limited to a force range here, so the comparison shows
    the extrapolation alone. Returns one row per horizon with the number of
    forecasts and both errors.
    """
    times = np.asarray(times, dtype=np.int64)
    horizons_ns = np.asarray(horizons_ms, dtype=np.int64) * 1_000_000
    errors = [([], []) for _ in horizons_ms]
    next_issue = times[0]
    for end in range(1, len(times)):
        if times[end] < next_issue:
            continue
        next_issue = times[end] + issue_ns
        first = np.searchsorted(times, times[end] - 2 * NS)
        values = forecast(times[first:end + 1], signal[first:end + 1], horizons_ns)
        if values is None:
            continue
        targets = times[end] + horizons_ns
        after = np.searchsorted(times, targets)
        for index, (target, right) in enumerate(zip(targets, after)):
            # The truth must be measured around the target, not bridged over a gap.
            if right >= len(times) or times[right] - times[right - 1] > MAX_GAP_NS:
                continue
            weight = (target - times[right - 1]) / (times[right] - times[right - 1])
            actual = truth[right - 1] + weight * (truth[right] - truth[right - 1])
            errors[index][0].append(values[index] - actual)
            errors[index][1].append(signal[end] - actual)
    rows = []
    for horizon, (forecast_error, hold_error) in zip(horizons_ms, errors):
        row = {'horizon_ms': int(horizon), 'forecasts': len(forecast_error)}
        if forecast_error:
            row['forecast_rmse_n'] = float(np.sqrt(np.mean(np.square(forecast_error))))
            row['hold_rmse_n'] = float(np.sqrt(np.mean(np.square(hold_error))))
        rows.append(row)
    return rows
