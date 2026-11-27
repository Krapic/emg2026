"""Check recording and model reports on synthetic recordings with a known grip."""

from uuid import uuid4

import numpy as np
import pytest

from shimmer_ros2 import grip_report
from shimmer_ros2.grip_data import EMG_DELAYS_MS, NS, write_csv, write_json

TOPIC = '/shimmer1/emg_processed'
FEATURE = f'{TOPIC}/ch1_mv'
FRAMES = {TOPIC: ['Shimmer_4C91'], '/grip_force_stream': ['grip']}
MVC_N = 200.0
DURATION_SEC = 20.0
# The synthetic EMG envelope is proportional to force, so this model is exact.
MV_PER_NEWTON = 0.01
REACTION_SEC = 0.4


def protocol_target(seconds):
    """Return the guided target in % MVC, timed as the recorder times its phases."""
    start = 0.0
    for target in [100, 0, 75, 0, 50, 0, 25, 0]:
        start += DURATION_SEC / (5 if target else 20)
        if seconds < start:
            return target
    return 0


def follows_cues(seconds):
    if seconds < REACTION_SEC:
        return 0.0
    return MVC_N * protocol_target(seconds - REACTION_SEC) / 100


def stays_at_rest(seconds):
    return -0.4


def save_recording(root, session, force_at, guided=True, created='2026-01-01T10:00:00+00:00'):
    recording_id = uuid4().hex
    directory = root / 'recordings' / recording_id
    directory.mkdir(parents=True)
    seconds = np.arange(0, DURATION_SEC, 1 / 200)
    stamps = np.round(seconds * NS).astype(np.int64)
    force = np.array([force_at(second) for second in seconds])
    phases, start = [], 0.0
    for target in [100, 0, 75, 0, 50, 0, 25, 0] if guided else []:
        end = start + DURATION_SEC / (5 if target else 20)
        phases.append({'target_percent_mvc': target, 'planned_start_ns': round(start * NS),
                       'planned_end_ns': round(end * NS)})
        start = end
    write_csv(directory / 'aligned.csv', ['stamp_ns', FEATURE, 'force_n'],
              zip(stamps.tolist(), (force * MV_PER_NEWTON).tolist(), force.tolist()))
    write_json(directory / 'metadata.json', {
        'version': 1, 'recording_id': recording_id, 'session': session, 'created_utc': created,
        'start_ns': 0, 'end_ns': round(DURATION_SEC * NS), 'phases': phases,
        'mvc_n': MVC_N if guided else None, 'emg_topics': [TOPIC], 'features': [FEATURE],
        'frame_ids': FRAMES, 'streams': {TOPIC: {'expected_hz': 512.0}},
    })
    return recording_id


def exact_model(offset_n=0.0):
    weights = [1 / MV_PER_NEWTON] + [0.0] * (len(EMG_DELAYS_MS) - 1)
    return {
        'features': [FEATURE], 'frame_ids': FRAMES, 'emg_hz': [512.0],
        'emg_delays_ms': list(EMG_DELAYS_MS), 'mean': [0.0] * len(weights),
        'scale': [1.0] * len(weights), 'intercept': offset_n, 'coefficients': weights,
        'created_utc': '2026-01-01T11:00:00+00:00',
    }


def test_recording_that_follows_the_cues_passes(tmp_path):
    report = grip_report.recording_report(
        tmp_path, save_recording(tmp_path, 'P01_pokus', follows_cues))
    assert (report['levels_followed'], report['levels_total']) == (4, 4)
    assert [phase['held_n'] for phase in report['phases']] == [200, 0, 150, 0, 100, 0, 50, 0]
    assert report['grip_share'] == pytest.approx(0.8, abs=0.01)
    assert grip_report.recording_warnings(report) == []


def test_recording_without_grip_is_flagged(tmp_path):
    report = grip_report.recording_report(
        tmp_path, save_recording(tmp_path, 'P01_pokus', stays_at_rest))
    assert (report['levels_followed'], report['levels_total']) == (0, 4)
    assert report['grip_share'] == 0
    # Rest phases were followed; only the missing grip levels are reported.
    assert [phase['followed'] for phase in report['phases']] == [False, True] * 4
    assert '0 od 4' in grip_report.recording_warnings(report)[0]


def test_free_recording_is_scaled_by_its_own_peak(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_mvc', follows_cues, guided=False)
    report = grip_report.recording_report(tmp_path, recording_id)
    assert report['mvc_n'] is None and report['reference_n'] == MVC_N
    assert report['phases'] == [] and grip_report.recording_warnings(report) == []


def test_unloaded_handle_is_not_scaled_into_a_grip(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_mvc', stays_at_rest, guided=False)
    report = grip_report.recording_report(tmp_path, recording_id)
    assert report['reference_n'] == grip_report.MIN_REFERENCE_N
    assert report['grip_share'] == 0


def test_recording_is_found_by_session_or_start_of_id(tmp_path):
    first = save_recording(tmp_path, 'P01_ucenje', follows_cues)
    second = save_recording(tmp_path, 'P01_validacija', follows_cues)
    assert grip_report.find_recording(tmp_path, 'P01_ucenje') == first
    assert grip_report.find_recording(tmp_path, second) == second
    assert grip_report.find_recording(tmp_path, second[:12]) == second
    with pytest.raises(ValueError, match='Nema snimke'):
        grip_report.find_recording(tmp_path, 'P02')


def test_repeated_session_label_asks_for_an_id(tmp_path):
    ids = [save_recording(tmp_path, 'P01_pokus', follows_cues) for _ in range(2)]
    with pytest.raises(ValueError, match='Zadajte ID') as error:
        grip_report.find_recording(tmp_path, 'P01_pokus')
    assert all(recording_id in str(error.value) for recording_id in ids)


def test_exact_model_has_no_error_at_any_level(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_pokus', follows_cues)
    result = grip_report.evaluate_model(tmp_path, exact_model(), recording_id)
    assert result['rmse_n'] == pytest.approx(0, abs=1e-9)
    assert sum(level['rows'] for level in result['levels']) == result['rows']
    assert all(level['rows'] > 0 for level in result['levels'])
    assert grip_report.evaluation_warnings(result) == []


def test_offset_model_shows_its_bias_at_every_level(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_pokus', follows_cues)
    result = grip_report.evaluate_model(tmp_path, exact_model(offset_n=10.0), recording_id)
    assert result['mae_n'] == pytest.approx(10.0)
    assert [level['bias_n'] for level in result['levels']] == pytest.approx([10.0] * 5)


def test_error_measured_only_at_rest_is_flagged(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_pokus', stays_at_rest)
    result = grip_report.evaluate_model(tmp_path, exact_model(), recording_id)
    assert [level['rows'] for level in result['levels']] == [result['rows'], 0, 0, 0, 0]
    assert 'mirovanje' in grip_report.evaluation_warnings(result)[0]


def test_model_from_another_sensor_is_rejected(tmp_path):
    recording_id = save_recording(tmp_path, 'P01_pokus', follows_cues)
    model = exact_model() | {'frame_ids': {**FRAMES, TOPIC: ['Shimmer_9D2C']}}
    with pytest.raises(ValueError, match='uređaje'):
        grip_report.evaluate_model(tmp_path, model, recording_id)


def test_newest_model_is_the_default(tmp_path):
    (tmp_path / 'models').mkdir()
    with pytest.raises(ValueError, match='Nema spremljenog modela'):
        grip_report.find_model(tmp_path)
    for name, created in [('aa11', '2026-01-02T00:00:00+00:00'),
                          ('bb22', '2026-01-01T00:00:00+00:00')]:
        write_json(tmp_path / 'models' / f'{name}.json', exact_model() | {'created_utc': created})
    assert grip_report.find_model(tmp_path)[0].stem == 'aa11'
    assert grip_report.find_model(tmp_path, 'bb')[0].stem == 'bb22'
    assert grip_report.find_model(tmp_path, str(tmp_path / 'models/bb22.json'))[0].stem == 'bb22'


def test_forecast_of_a_steady_wave_beats_holding_the_estimate(tmp_path):
    recording_id = save_recording(
        tmp_path, 'P01_val', lambda seconds: 100 + 80 * np.sin(2 * np.pi * 0.4 * seconds),
        guided=False)
    report = grip_report.forecast_report(tmp_path, exact_model(), recording_id, [250, 500])
    assert report['session'] == 'P01_val' and report['grip_share'] > 0.8
    for rows in (report['against_estimate'], report['against_force']):
        assert [row['horizon_ms'] for row in rows] == [250, 500]
        assert all(row['forecast_rmse_n'] < 0.1 * row['hold_rmse_n'] for row in rows)
