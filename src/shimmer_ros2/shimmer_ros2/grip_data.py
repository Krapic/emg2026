"""Timestamp alignment and baseline fitting for grip recordings."""

import csv
import json
import re
from pathlib import Path

import numpy as np

NS = 1_000_000_000
ID_PATTERN = re.compile(r'[0-9a-f]{32}')
EMG_DELAYS_MS = (0, 50, 100, 200, 350, 500)
MAX_EMG_GAP_NS = 20_000_000


def summarize(rows, expected_hz):
    stamps = np.array([row[0] for row in rows], dtype=np.int64)
    if len(stamps) < 2:
        raise ValueError('Premalo uzoraka u toku.')
    gaps = np.diff(stamps)
    span = (int(stamps.max()) - int(stamps.min())) / NS
    if span <= 0:
        raise ValueError('Vremenske oznake nemaju raspon.')
    observed_hz = (len(np.unique(stamps)) - 1) / span
    received = np.array([row[1] for row in rows], dtype=np.int64)
    receipt_span = (int(received.max()) - int(received.min())) / NS
    delays_ms = (received - stamps) / 1e6
    return {
        'samples': len(rows),
        'expected_hz': expected_hz,
        'observed_hz': observed_hz,
        'frequency_error_percent': 100 * (observed_hz / expected_hz - 1),
        'received_hz': (len(rows) - 1) / receipt_span if receipt_span > 0 else None,
        'median_receipt_delay_ms': float(np.median(delays_ms)),
        'p95_receipt_delay_ms': float(np.percentile(delays_ms, 95)),
        'non_increasing': int(np.count_nonzero(gaps <= 0)),
        'max_gap_ms': float(np.max(np.diff(np.unique(stamps)))) / 1e6,
    }


def ordered(rows):
    stamps = np.array([row[0] for row in rows], dtype=np.int64)
    values = np.array([row[3:] for row in rows], dtype=float)
    unique, indices = np.unique(stamps, return_index=True)
    return unique, values[indices]


def align(emg_streams, force_rows, max_gap_ns):
    """Use force timestamps and interpolate only inside short EMG brackets."""
    times, force = ordered(force_rows)
    valid = np.isfinite(force[:, 0])
    columns = []
    for stream in emg_streams:
        stamps, emg = ordered(stream)
        values, supported = interpolate(times, stamps, emg, max_gap_ns)
        valid &= supported
        columns.append(values)
    return times[valid], np.column_stack(columns)[valid], force[valid, 0]


def interpolate(times, stamps, values, max_gap_ns):
    """Interpolate inside short brackets of an ordered, nonempty EMG stream."""
    right = np.searchsorted(stamps, times, side='left')
    hi = np.minimum(right, len(stamps) - 1)
    exact = stamps[hi] == times
    lo = np.where(exact, hi, np.maximum(right - 1, 0))
    gap = stamps[hi] - stamps[lo]
    valid = exact | ((right > 0) & (right < len(stamps)) & (gap <= max_gap_ns))
    valid &= np.isfinite(values[lo]).all(axis=1) & np.isfinite(values[hi]).all(axis=1)
    weight = np.where(valid, times - stamps[lo], 0) / np.maximum(gap, 1)
    return values[lo] + weight[:, None] * (values[hi] - values[lo]), valid


def feature_names(topics):
    return [f'{topic}/ch1_mv' for topic in topics]


def delayed_emg(times, streams, delays_ms, max_gap_ns):
    """Build causal regressors ordered by delay, then by EMG channel."""
    queries = times[:, None] - np.asarray(delays_ms, dtype=np.int64) * 1_000_000
    valid = np.ones(len(times), dtype=bool)
    columns = []
    for stamps, values in streams:
        samples, supported = interpolate(queries.ravel(), stamps, values, max_gap_ns)
        valid &= supported.reshape(queries.shape).all(axis=1)

        # Even when both ends are valid samples, never join history across an outage.
        finite = np.isfinite(values).all(axis=1)
        breaks = (np.diff(stamps) > max_gap_ns) | ~finite[:-1] | ~finite[1:]
        cumulative_breaks = np.r_[0, np.cumsum(breaks)]
        first = np.searchsorted(stamps, queries[:, -1], side='right') - 1
        last = np.searchsorted(stamps, times, side='left')
        valid &= (cumulative_breaks[np.clip(first, 0, len(stamps) - 1)]
                  == cumulative_breaks[np.clip(last, 0, len(stamps) - 1)])
        columns.append(samples.reshape(len(times), len(delays_ms), values.shape[1]))
    design = np.concatenate(columns, axis=2)
    return design.reshape(len(times), len(delays_ms) * design.shape[2]), valid


def predict(x, mean, scale, intercept, coefficients):
    return (x - mean) / scale @ coefficients + intercept


def write_csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + '\n',
                    encoding='utf-8')


def load_recording(root, recording_id):
    if not ID_PATTERN.fullmatch(recording_id):
        raise ValueError(f'Neispravan identifikator snimke: {recording_id}')
    directory = Path(root) / 'recordings' / recording_id
    metadata = json.loads((directory / 'metadata.json').read_text(encoding='utf-8'))
    recorded_features = metadata['features']
    topics = metadata['emg_topics']
    features = feature_names(topics)
    if (metadata['version'] != 1 or not features
            or len(set(recorded_features)) != len(recorded_features)
            or not all(name in recorded_features for name in features)):
        raise ValueError('Nepodržan format snimke.')
    header = ['stamp_ns', *recorded_features, 'force_n']
    indices = [header.index(name) for name in features]
    stamps = []
    rows = []
    with (directory / 'aligned.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.reader(stream)
        if next(reader, None) != header:
            raise ValueError('Stupci snimke ne odgovaraju metapodacima.')
        for row in reader:
            if len(row) != len(header):
                raise ValueError('Snimka ima neispravan broj stupaca.')
            stamps.append(int(row[0]))
            rows.append([*(float(row[index]) for index in indices), float(row[-1])])
    stamps = np.asarray(stamps, dtype=np.int64)
    rows = np.asarray(rows, dtype=float)
    if len(rows) < 50 or not np.isfinite(rows).all() or np.any(np.diff(stamps) <= 0):
        raise ValueError('Snimka nema dovoljno valjanih redaka.')
    emg_hz = [metadata['streams'][topic]['expected_hz'] for topic in topics]
    return (features, metadata['frame_ids'], emg_hz), stamps, rows[:, :-1], rows[:, -1]


def fit_model(x, y, alpha):
    if np.ptp(y) < 1.0:
        raise ValueError('Sila u snimkama za učenje mora varirati barem 1 N.')
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    if not np.any(scale > 1e-9):
        raise ValueError('EMG značajke nemaju varijaciju.')
    scale[scale <= 1e-9] = 1
    z = (x - mean) / scale
    intercept = float(y.mean())
    # Solve the augmented ridge system directly without squaring its condition number.
    design = np.vstack((z, np.sqrt(alpha) * np.eye(z.shape[1])))
    target = np.concatenate((y - intercept, np.zeros(z.shape[1])))
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    return mean, scale, intercept, coefficients


def metrics(y, prediction):
    error = y - prediction
    return {
        'mae_n': float(np.mean(np.abs(error))),
        'rmse_n': float(np.sqrt(np.mean(error ** 2))),
    }
