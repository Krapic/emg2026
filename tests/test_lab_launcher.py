"""Safety and freshness checks for the hardware launcher, without Bluetooth writes."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
# The launcher imports the report next to it, as it does when run as a script.
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('lab_launcher', SCRIPTS / 'lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class LauncherTests(unittest.TestCase):
    def test_existing_correct_binding_is_reused(self):
        with patch.object(lab, 'run', return_value=(
                'rfcomm1: 60:8A:10:40:9D:2C channel 6 connected [tty-attached]')) as run:
            self.assertFalse(lab.needs_binding(1, '60:8A:10:40:9D:2C', 6))
            self.assertEqual(run.call_count, 1)

    def test_wrong_active_binding_is_never_released(self):
        with patch.object(lab, 'run', return_value=(
                'rfcomm1: 00:00:00:00:00:01 channel 1 connected [tty-attached]')) as run:
            with self.assertRaisesRegex(RuntimeError, 'zauzet'):
                lab.needs_binding(1, '60:8A:10:40:9D:2C', 6)
            self.assertEqual(run.call_count, 1)

    def test_closed_wrong_channel_needs_rebinding(self):
        with patch.object(lab, 'run', return_value=(
                'rfcomm1: 60:8A:10:40:9D:2C channel 1 closed')):
            self.assertTrue(lab.needs_binding(1, '60:8A:10:40:9D:2C', 6))

    def test_reused_pid_is_not_signalled(self):
        record = {'pid': os.getpid(), 'start': 'incorrect-start-ticks'}
        with patch.object(lab.os, 'killpg') as kill:
            lab.stop_owned([record])
            kill.assert_not_called()

    def test_shutdown_does_not_touch_an_unowned_process(self):
        owned = subprocess.Popen(['sleep', '30'], start_new_session=True)
        other = subprocess.Popen(['sleep', '30'], start_new_session=True)
        try:
            record = {'pid': owned.pid, 'start': lab.process_identity(owned.pid)}
            lab.stop_owned([record])
            owned.wait(timeout=2)
            self.assertIsNotNone(owned.returncode)
            self.assertIsNone(other.poll())
        finally:
            for child in [owned, other]:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=2)

    def test_stale_or_wrong_sensor_is_not_ready(self):
        monitor = object.__new__(lab.Monitor)
        topic = '/shimmer1/emg_stream'
        monitor.topics = {topic: 'Shimmer_4C91'}
        monitor.samples = {topic: [100, time.monotonic() - 10, 'Shimmer_4C91']}
        self.assertFalse(monitor.ready(topic))
        monitor.samples[topic] = [3, time.monotonic(), 'Shimmer_4C91']
        self.assertTrue(monitor.ready(topic))
        monitor.samples[topic][2] = 'Shimmer_9D23'
        with self.assertRaisesRegex(RuntimeError, 'frame_id'):
            monitor.ready(topic)


class RecordingNameTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)

    def save(self, recording_id, session):
        directory = self.root / 'recordings' / recording_id
        directory.mkdir(parents=True)
        (directory / 'metadata.json').write_text(json.dumps({
            'recording_id': recording_id, 'session': session,
            'created_utc': '2026-01-01T10:00:00+00:00'}))

    def test_session_label_and_start_of_id_resolve_to_the_id(self):
        self.save('a' * 32, 'P01_mvc')
        self.save('b' * 32, 'P01_pokus1')
        self.assertEqual(lab.resolve_recording('P01_pokus1', self.root), 'b' * 32)
        self.assertEqual(lab.resolve_recording('aaaa', self.root), 'a' * 32)

    def test_full_id_is_left_for_the_service_to_check(self):
        self.assertEqual(lab.resolve_recording('c' * 32, self.root / 'missing'), 'c' * 32)

    def test_repeated_or_unknown_label_is_refused(self):
        self.save('a' * 32, 'P01_pokus1')
        self.save('b' * 32, 'P01_pokus1')
        with self.assertRaisesRegex(ValueError, 'Zadajte ID'):
            lab.resolve_recording('P01_pokus1', self.root)
        with self.assertRaisesRegex(ValueError, 'Nema snimke'):
            lab.resolve_recording('P02', self.root)


if __name__ == '__main__':
    unittest.main()
