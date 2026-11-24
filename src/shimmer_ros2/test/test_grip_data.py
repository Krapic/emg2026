"""Check alignment, delayed features and ridge fitting on signals with known answers."""

import numpy as np
import pytest

from shimmer_ros2.grip_data import (
    align, delayed_emg, EMG_DELAYS_MS, fit_model, interpolate, MAX_EMG_GAP_NS, metrics,
    predict, summarize,
)

MS = 1_000_000


def ramp(*milliseconds):
    """Return an EMG stream sampled every 2 ms whose value is its own time in ms."""
    stamps = np.concatenate([np.arange(start, end + 1, 2) for start, end in milliseconds]) * MS
    return stamps, (stamps / MS)[:, None]


def test_interpolates_linearly_between_neighbours():
    stamps = np.array([0, 10, 20]) * MS
    values = np.array([[0.0], [1.0], [3.0]])
    result, valid = interpolate(np.array([5, 10, 15]) * MS, stamps, values, MAX_EMG_GAP_NS)
    assert valid.all()
    np.testing.assert_allclose(result[:, 0], [0.5, 1.0, 2.0])


def test_does_not_extrapolate_or_bridge_a_long_gap():
    stamps = np.array([0, 10, 50]) * MS
    values = np.array([[0.0], [1.0], [2.0]])
    before, inside_gap, after, on_sample = np.array([-5, 30, 60, 50]) * MS
    _, valid = interpolate(np.array([before, inside_gap, after, on_sample]), stamps, values,
                           MAX_EMG_GAP_NS)
    assert valid.tolist() == [False, False, False, True]


def test_align_keeps_force_samples_that_emg_supports():
    stamps, values = ramp((0, 100))
    emg = [(stamp, 0, 'Shimmer_4C91', value) for stamp, value in zip(stamps, values[:, 0])]
    force = [(time * MS, 0, 'grip', newtons) for time, newtons in
             [(-5, 1.0), (5, 50.0), (15, 150.0), (25, float('nan')), (105, 9.0)]]
    times, x, y = align([emg], force, MAX_EMG_GAP_NS)
    assert times.tolist() == [5 * MS, 15 * MS]
    np.testing.assert_allclose(x[:, 0], [5.0, 15.0])
    assert y.tolist() == [50.0, 150.0]


def test_delayed_features_read_the_signal_at_each_delay():
    times = np.array([400, 500, 800]) * MS
    design, valid = delayed_emg(times, [ramp((0, 1000))], EMG_DELAYS_MS, MAX_EMG_GAP_NS)
    # The first estimate needs the full 500 ms of history.
    assert valid.tolist() == [False, True, True]
    np.testing.assert_allclose(design[1], [500, 450, 400, 300, 150, 0])
    np.testing.assert_allclose(design[2], [800, 750, 700, 600, 450, 300])


def test_history_is_not_joined_across_an_outage():
    stream = ramp((0, 600), (700, 1500))
    # At 900 ms every delayed sample exists, but the 500 ms of history spans the outage.
    times = np.array([600, 900, 1250]) * MS
    _, valid = delayed_emg(times, [stream], EMG_DELAYS_MS, MAX_EMG_GAP_NS)
    assert valid.tolist() == [True, False, True]


def test_ridge_recovers_a_linear_relation():
    x = np.random.default_rng(0).normal(size=(500, 3))
    y = 20 + x @ np.array([5.0, -2.0, 0.5])
    mean, scale, intercept, coefficients = fit_model(x, y, alpha=1e-9)
    np.testing.assert_allclose(predict(x, mean, scale, intercept, coefficients), y, atol=1e-6)


def test_stronger_ridge_shrinks_coefficients():
    x = np.random.default_rng(0).normal(size=(500, 3))
    y = 20 + x @ np.array([5.0, -2.0, 0.5])
    weak = fit_model(x, y, alpha=1.0)[3]
    strong = fit_model(x, y, alpha=1000.0)[3]
    assert np.linalg.norm(strong) < np.linalg.norm(weak)


def test_fit_rejects_data_without_variation():
    x = np.random.default_rng(0).normal(size=(100, 3))
    with pytest.raises(ValueError, match='Sila'):
        fit_model(x, np.full(100, 30.0), alpha=1.0)
    with pytest.raises(ValueError, match='EMG'):
        fit_model(np.ones((100, 3)), np.linspace(0, 100, 100), alpha=1.0)


def test_metrics_are_in_newtons():
    result = metrics(np.zeros(4), np.array([1.0, -1.0, 3.0, -3.0]))
    assert result == {'mae_n': 2.0, 'rmse_n': pytest.approx(5 ** 0.5)}


def test_summary_compares_expected_and_observed_rate():
    # 100 Hz samples, each received 5 ms after its timestamp.
    rows = [(index * 10 * MS, index * 10 * MS + 5 * MS, 'grip', 0.0) for index in range(101)]
    summary = summarize(rows, expected_hz=200.0)
    assert summary['observed_hz'] == pytest.approx(100.0)
    assert summary['frequency_error_percent'] == pytest.approx(-50.0)
    assert summary['median_receipt_delay_ms'] == pytest.approx(5.0)
    assert summary['max_gap_ms'] == pytest.approx(10.0)
