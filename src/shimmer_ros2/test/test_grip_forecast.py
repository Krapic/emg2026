"""Check the Hankel-DMD forecast on signals whose continuation is known."""

import numpy as np
import pytest

from shimmer_ros2 import grip_forecast
from shimmer_ros2.grip_data import NS

STEP_NS = 5_000_000  # The estimator publishes at 200 Hz.


def damped_wave(seconds):
    return 50 + 30 * np.exp(-0.8 * seconds) * np.cos(2 * np.pi * 0.7 * seconds)


def slow_wave(seconds):
    return 50 + 35 * np.sin(2 * np.pi * 0.45 * seconds)


def test_continues_a_damped_oscillation_with_an_offset():
    seconds = np.arange(40) / grip_forecast.FORECAST_HZ
    ahead = np.array([0.1, 0.25, 0.5])
    forecast = grip_forecast.hankel_dmd(damped_wave(seconds), ahead * grip_forecast.FORECAST_HZ)
    assert forecast == pytest.approx(damped_wave(seconds[-1] + ahead), abs=1e-6)


def test_zero_step_returns_the_last_sample():
    series = slow_wave(np.arange(40) / grip_forecast.FORECAST_HZ)
    assert grip_forecast.hankel_dmd(series, [0.0])[0] == pytest.approx(series[-1])


def test_constant_and_empty_signals_stay_where_they_are():
    assert grip_forecast.hankel_dmd(np.full(40, -0.4), [4, 20]) == pytest.approx([-0.4, -0.4])
    assert grip_forecast.hankel_dmd(np.zeros(40), [4, 20]) == pytest.approx([0, 0])


def test_growth_inside_the_window_does_not_run_away():
    seconds = np.arange(40) / grip_forecast.FORECAST_HZ
    series = np.exp(3 * seconds)
    forecast = grip_forecast.hankel_dmd(series, [200.0])[0]
    # Five seconds of unchecked growth would reach millions.
    assert series[-1] <= forecast < 10 * series[-1]


def test_history_needs_a_full_window_without_outages():
    stamps = np.arange(400) * STEP_NS
    values = slow_wave(stamps / NS)
    short = grip_forecast.WINDOW_SAMPLES * grip_forecast.PERIOD_NS // STEP_NS - 10
    assert grip_forecast.recent_history(stamps[:short], values[:short]) is None
    outage = np.r_[stamps[:300], stamps[320:]]
    assert grip_forecast.recent_history(outage, slow_wave(outage / NS)) is None
    history = grip_forecast.recent_history(stamps, values)
    assert len(history) == grip_forecast.WINDOW_SAMPLES
    assert history[-1] == values[-1]
    assert history[0] == pytest.approx(
        slow_wave((stamps[-1] - (len(history) - 1) * grip_forecast.PERIOD_NS) / NS))


def test_forecast_follows_a_wave_and_respects_bounds():
    stamps = 1_700_000_000 * NS + np.arange(400) * STEP_NS
    seconds = np.arange(400) * STEP_NS / NS
    horizons = np.array([100, 250, 500]) * 1_000_000
    forecast = grip_forecast.forecast(stamps, slow_wave(seconds), horizons)
    assert forecast == pytest.approx(slow_wave(seconds[-1] + horizons / NS), abs=0.01)
    limited = grip_forecast.forecast(stamps, slow_wave(seconds), horizons, bounds=(40.0, 45.0))
    assert limited.min() >= 40 and limited.max() <= 45
    assert grip_forecast.forecast(stamps[:50], slow_wave(seconds[:50]), horizons) is None


def test_comparison_shows_the_gain_over_holding_the_last_value():
    stamps = np.arange(2000) * STEP_NS
    signal = slow_wave(stamps / NS)
    rows = grip_forecast.compare(stamps, signal, signal)
    assert [row['horizon_ms'] for row in rows] == [100, 250, 500]
    for row in rows:
        assert row['forecasts'] > 100
        assert row['forecast_rmse_n'] < 0.05 < row['hold_rmse_n']
    assert rows[0]['hold_rmse_n'] < rows[2]['hold_rmse_n']


def test_comparison_skips_targets_inside_an_outage():
    stamps = np.arange(2000) * STEP_NS
    kept = np.r_[stamps[:1000], stamps[1200:]]
    signal = slow_wave(kept / NS)
    complete = grip_forecast.compare(stamps, slow_wave(stamps / NS), slow_wave(stamps / NS))
    broken = grip_forecast.compare(kept, signal, signal)
    assert all(b['forecasts'] < c['forecasts'] for b, c in zip(broken, complete))
    assert all(row['forecast_rmse_n'] < 0.05 for row in broken)
