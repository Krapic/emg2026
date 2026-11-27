"""Report whether a recording holds the grip it was meant to and how a model does on it.

Uses only NumPy, so the same checks run offline and can be called from the ROS services.
"""

import json
from pathlib import Path

import numpy as np

from shimmer_ros2.grip_data import (
    ID_PATTERN, MAX_EMG_GAP_NS, NS, delayed_emg, load_recording, metrics, predict,
)
from shimmer_ros2.grip_forecast import HORIZONS_MS, compare

# Force above this share of the reference counts as gripping: halfway between
# rest and the lowest level of the guided protocol (25 % MVC).
GRIP_THRESHOLD = 0.125
# A guided phase counts as followed when the held force is this close to its
# target, as a share of the reference.
PHASE_TOLERANCE = 0.15
# One level of the guided protocol lasts a fifth of the recording. With less
# gripping than that, error metrics mostly describe rest.
MIN_GRIP_SHARE = 0.2
# A recording without a stated MVC is scaled by its own peak, but a peak this
# weak is the unloaded handle rather than a grip.
MIN_REFERENCE_N = 20.0
# Bands centred on the protocol levels, as shares of the reference force.
LEVELS = (
    ('mirovanje', -np.inf, 0.125),
    ('oko 25 %', 0.125, 0.375),
    ('oko 50 %', 0.375, 0.625),
    ('oko 75 %', 0.625, 0.875),
    ('oko 100 %', 0.875, np.inf),
)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def list_recordings(root):
    """Return the metadata of every saved recording, oldest first."""
    paths = (Path(root) / 'recordings').glob('*/metadata.json')
    saved = [read_json(path) for path in paths if ID_PATTERN.fullmatch(path.parent.name)]
    return sorted(saved, key=lambda metadata: metadata['created_utc'])


def find_recording(root, name):
    """Resolve a session label, an ID or the start of an ID to one recording ID."""
    recordings = list_recordings(root)
    matches = [m for m in recordings if name in (m['session'], m['recording_id'])]
    matches = matches or [m for m in recordings if m['recording_id'].startswith(name)]
    if not matches:
        raise ValueError(f'Nema snimke "{name}" u {Path(root) / "recordings"}.')
    if len(matches) > 1:
        choices = ', '.join(f"{m['recording_id']} ({m['created_utc'][:16]})" for m in matches)
        raise ValueError(f'Više snimki odgovara oznaci "{name}". Zadajte ID: {choices}')
    return matches[0]['recording_id']


def list_models(root):
    """Return (path, model) of every saved model, oldest first."""
    models = [(path, read_json(path)) for path in (Path(root) / 'models').glob('*.json')]
    return sorted(models, key=lambda item: item[1]['created_utc'])


def find_model(root, name=None):
    """Return (path, model) for a file, an ID or its start; the newest model when omitted."""
    if name and Path(name).is_file():
        return Path(name), read_json(name)
    models = [item for item in list_models(root) if item[0].stem.startswith(name or '')]
    if not models:
        raise ValueError(f'Nema modela "{name}".' if name else 'Nema spremljenog modela.')
    if name and len(models) > 1:
        raise ValueError(f'Više modela počinje s "{name}". Zadajte cijeli ID.')
    return models[-1]


def reference_force(metadata, force):
    """Return the MVC the targets used; a free recording is scaled by its own peak."""
    return metadata['mvc_n'] or max(float(force.max()), MIN_REFERENCE_N)


def recording_report(root, recording_id):
    """Summarize the measured force and compare it with each guided target.

    The held force of a phase is the median over its second half, which leaves
    the first half for the reaction to the cue and the change of force.
    """
    metadata = read_json(Path(root) / 'recordings' / recording_id / 'metadata.json')
    _, stamps, _, force = load_recording(root, recording_id)
    reference = reference_force(metadata, force)
    phases = []
    for phase in metadata['phases']:
        start, end = phase['planned_start_ns'], phase['planned_end_ns']
        held = force[(stamps >= (start + end) // 2) & (stamps < end)]
        target_n = phase['target_percent_mvc'] / 100 * reference
        held_n = float(np.median(held)) if len(held) else None
        phases.append({
            'target_percent': phase['target_percent_mvc'], 'target_n': target_n,
            'held_n': held_n,
            'followed': (held_n is not None
                         and abs(held_n - target_n) <= PHASE_TOLERANCE * reference),
        })
    levels = [phase for phase in phases if phase['target_percent']]
    return {
        'recording_id': recording_id, 'session': metadata['session'],
        'created_utc': metadata['created_utc'],
        'duration_sec': (metadata['end_ns'] - metadata['start_ns']) / NS,
        'mvc_n': metadata['mvc_n'], 'reference_n': reference,
        'peak_n': float(force.max()),
        'grip_share': float(np.mean(force > GRIP_THRESHOLD * reference)),
        'phases': phases, 'levels_total': len(levels),
        'levels_followed': sum(phase['followed'] for phase in levels),
    }


def recording_warnings(report):
    if report['levels_followed'] < report['levels_total']:
        return [f"praćeno je {report['levels_followed']} od {report['levels_total']} "
                'zadanih razina stiska']
    return []


def estimate_recording(root, model, recording_id):
    """Apply a saved model to one recording.

    Returns the metadata, the reference force and, for every row with enough
    EMG history, the time, the measured force and the estimate.
    """
    schema, times, emg, force = load_recording(root, recording_id)
    if schema != (model['features'], model['frame_ids'], model['emg_hz']):
        raise ValueError('Model i snimka nemaju iste EMG značajke, uređaje i frekvenciju.')
    metadata = read_json(Path(root) / 'recordings' / recording_id / 'metadata.json')
    reference = reference_force(metadata, force)
    design, valid = delayed_emg(times, [(times, emg)], model['emg_delays_ms'], MAX_EMG_GAP_NS)
    if not valid.any():
        raise ValueError(f'Snimka {recording_id} nema dovoljno neprekinute EMG povijesti.')
    estimate = predict(design[valid], np.asarray(model['mean']), np.asarray(model['scale']),
                       model['intercept'], np.asarray(model['coefficients']))
    return metadata, reference, times[valid], force[valid], estimate


def evaluate_model(root, model, recording_id):
    """Return a saved model's error on one recording, overall and by force level."""
    metadata, reference, _, force, estimate = estimate_recording(root, model, recording_id)
    share = force / reference
    levels = []
    for name, low, high in LEVELS:
        rows = (share >= low) & (share < high)
        level = {'name': name, 'rows': int(rows.sum())}
        if rows.any():
            level.update(metrics(force[rows], estimate[rows]))
            # Positive when the model estimates more force than was measured.
            level['bias_n'] = float(np.mean(estimate[rows] - force[rows]))
        levels.append(level)
    return {
        'recording_id': recording_id, 'session': metadata['session'], 'rows': len(force),
        **metrics(force, estimate), 'reference_n': reference,
        'grip_share': float(np.mean(share > GRIP_THRESHOLD)), 'levels': levels,
    }


def evaluation_warnings(evaluation):
    if evaluation['grip_share'] < MIN_GRIP_SHARE:
        return [f"stisak je u samo {100 * evaluation['grip_share']:.0f} % redaka, "
                'pa pogreška opisuje uglavnom mirovanje']
    return []


def forecast_report(root, model, recording_id, horizons_ms=HORIZONS_MS):
    """Score the forecast of a model's estimate on one recording.

    Each horizon gets two comparisons with holding the last estimate: against
    the later estimate, which isolates the forecast, and against the measured
    force, which also carries the error of the estimate itself.
    """
    metadata, reference, times, force, estimate = estimate_recording(root, model, recording_id)
    return {
        'recording_id': recording_id, 'session': metadata['session'],
        'grip_share': float(np.mean(force > GRIP_THRESHOLD * reference)),
        'against_estimate': compare(times, estimate, estimate, horizons_ms),
        'against_force': compare(times, estimate, force, horizons_ms),
    }
