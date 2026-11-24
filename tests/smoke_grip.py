"""Run the actual launcher and ROS services with synthetic inputs and isolated storage."""

import csv
import json
import math
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import rclpy
from rclpy.node import Node

from emg_grip_interfaces.msg import Emg, GripForce

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / 'scripts/lab.py'
NS = 1_000_000_000
SENSORS = ('Shimmer_4C91', 'Shimmer_9D2C', 'Shimmer_4C87', 'Shimmer_9D23')


class Fixture(Node):
    def __init__(self, emg_hz, shimmers):
        super().__init__('synthetic_grip_fixture')
        self.declare_parameter('sampling_rate', emg_hz)
        self.emg_hz = emg_hz
        self.shimmers = shimmers
        self.emg = [self.create_publisher(Emg, f'/shimmer{i}/emg_stream', 2048)
                    for i in shimmers]
        self.force = self.create_publisher(GripForce, '/grip_force_stream', 1024)
        self.create_subscription(GripForce, '/grip_force_estimated', self.receive, 1024)
        self.anchor = self.get_clock().now().nanoseconds
        self.start = time.monotonic()
        self.next_index = [0, 0]
        self.estimates = []
        self.pause_first = False
        self.create_timer(0.005, self.publish_samples)

    @staticmethod
    def force_at(t):
        return 50 + 35 * math.sin(2 * math.pi * 0.45 * t)

    def publish_samples(self):
        elapsed = time.monotonic() - self.start
        for stream, hz in enumerate((self.emg_hz, 200)):
            while self.next_index[stream] / hz <= elapsed:
                t = self.next_index[stream] / hz
                self.next_index[stream] += 1
                stamp = self.anchor + round(t * NS)
                force = self.force_at(t)
                if stream == 0:
                    for i, publisher in enumerate(self.emg):
                        if i == 0 and self.pause_first:
                            continue
                        msg = Emg()
                        msg.header.frame_id = SENSORS[self.shimmers[i] - 1]
                        msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, NS)
                        msg.emg_ch1 = 16 + force / 40 * math.sin(2 * math.pi * 80 * t + i)
                        msg.emg_ch2 = float('nan')  # Channel 2 must be ignored everywhere.
                        publisher.publish(msg)
                else:
                    msg = GripForce()
                    msg.header.frame_id = 'grip'
                    msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(stamp, NS)
                    msg.grip_force = force
                    self.force.publish(msg)

    def receive(self, msg):
        stamp = msg.header.stamp.sec * NS + msg.header.stamp.nanosec
        self.estimates.append((stamp, msg.grip_force, self.get_clock().now().nanoseconds))

    def wait(self, condition, seconds):
        deadline = time.monotonic() + seconds
        while not condition() and time.monotonic() < deadline:
            rclpy.spin_once(self, timeout_sec=0.02)
        return condition()


def run_test(node, directory):
    data_dir = directory / 'data'
    state_dir = directory / 'state'
    state_dir.mkdir()
    launcher_log = directory / 'launcher.log'
    # Publishers already exist in the isolated ROS graph. Bypass only physical preparation.
    bootstrap = (
        'import sys; from pathlib import Path; '
        'sys.path.insert(0, sys.argv.pop(1)); import lab; '
        'lab.STATE_DIR = Path(sys.argv.pop(1)); lab.STATE = lab.STATE_DIR / "state.json"; '
        'lab.prepare = lambda devices: None; sys.exit(lab.main())'
    )
    selection = ['--shimmers', *map(str, node.shimmers)] if len(node.shimmers) > 1 else []
    with launcher_log.open('w') as log:
        launcher = subprocess.Popen(
            [sys.executable, '-c', bootstrap, str(LAB.parent), str(state_dir),
             'start', '--no-gui', '--data-dir', str(data_dir), '--emg-hz', str(node.emg_hz),
             *selection],
            stdout=log, stderr=subprocess.STDOUT)

    def cli(*args, timeout=45, success=True):
        with (directory / 'command.log').open('w+') as output:
            process = subprocess.Popen([sys.executable, str(LAB), *args],
                                       stdout=output, stderr=subprocess.STDOUT)
            try:
                if not node.wait(lambda: process.poll() is not None, timeout):
                    raise RuntimeError(f'Isteklo čekanje: {args}')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
            output.seek(0)
            result = output.read()
            assert (process.returncode == 0) == success, result
            return result

    try:
        assert node.wait(lambda: 'SPREMNO.' in launcher_log.read_text()
                         or launcher.poll() is not None, 20), launcher_log.read_text()
        assert 'SPREMNO.' in launcher_log.read_text(), launcher_log.read_text()
        state = json.loads((state_dir / 'state.json').read_text())
        assert state['shimmers'] == node.shimmers, state
        print('Pokretač, obrada i servisi spremni na sintetičkim tokovima.', flush=True)
        ids = []
        for session in ('synthetic_train', 'synthetic_validate'):
            result = cli('record', session, '--duration', '20', '--mvc', '100')
            assert 'Cilj: 100% (100 N)' in result and 'Cilj: 25% (25 N)' in result, result
            # The synthetic force is a sine, so it cannot hold all four levels.
            assert 'DRŽANO [N]' in result and 'zadanih razina stiska' in result, result
            recording_id = next(line.split()[-1] for line in result.splitlines()
                                if line.startswith('ID snimke:'))
            ids.append(recording_id)
            recording = data_dir / 'recordings' / recording_id
            meta = json.loads((recording / 'metadata.json').read_text())
            assert meta['mvc_n'] == 100 and meta['session'] == session, meta
            assert [p['target_n'] for p in meta['phases']] == [100, 0, 75, 0, 50, 0, 25, 0]
            assert meta['coverage_fraction'] > 0.95, meta
            assert all(abs(s['frequency_error_percent']) < 3 for s in meta['streams'].values())
            names = ['force', 'aligned']
            names.extend(f'{prefix}emg{i}' for i in range(1, len(node.emg) + 1)
                         for prefix in ('', 'raw_'))
            for name in names:
                with (recording / f'{name}.csv').open() as stream:
                    reader = csv.reader(stream)
                    assert all('ch2' not in column for column in next(reader)), name
                    assert sum(1 for _ in reader) > 3500, name
            print(f'{session}: {meta["aligned_rows"]} redaka, '
                  f'{meta["coverage_fraction"]:.1%} pokrivenosti.', flush=True)
        # Session labels are looked up locally, so the command needs the test's data directory.
        result = cli('train', 'synthetic_train', '--validation', ids[1][:8], '--activate',
                     '--data-dir', str(data_dir))
        model_path = next(line.removeprefix('Model: ') for line in result.splitlines()
                          if line.startswith('Model: '))
        assert 'synthetic_validate (validacija)' in result and 'RAZINA SILE' in result, result
        model = json.loads(Path(model_path).read_text())
        assert all(feature.endswith('/ch1_mv') for feature in model['features'])
        assert model['emg_delays_ms'][-1] == 500
        assert model['validation_metrics']['rmse_n'] < 15, result
        assert node.wait(lambda: len(node.estimates) >= 250, 5), 'Nema procjena.'
        assert all(b[0] > a[0] for a, b in zip(node.estimates, node.estimates[1:]))
        rmse = math.sqrt(sum(
            (value - node.force_at((stamp - node.anchor) / NS)) ** 2
            for stamp, value, _ in node.estimates) / len(node.estimates))
        assert rmse < 15, rmse
        age_ms = sorted((received - stamp) / 1e6 for stamp, _, received in node.estimates)
        bad = directory / 'bad.json'
        bad.write_text('{}')
        cli('estimate', str(bad), success=False)
        count = len(node.estimates)
        assert node.wait(lambda: len(node.estimates) > count, 3)
        node.pause_first = True
        node.wait(lambda: False, 3)
        count = len(node.estimates)
        assert 'Nema svježih podataka' in cli('record', 'missing', '--free', success=False)
        assert len(node.estimates) == count
        node.pause_first = False
        assert node.wait(lambda: len(node.estimates) > count, 4), 'Nema oporavka procjena.'
        print(f'Validacija RMSE {model["validation_metrics"]["rmse_n"]:.2f} N, '
              f'uživo RMSE {rmse:.2f} N, medijan starosti {age_ms[len(age_ms) // 2]:.0f} ms. '
              'Provjereni nevaljan model, prekid i povratak senzora.', flush=True)
    finally:
        if launcher.poll() is None:
            launcher.send_signal(signal.SIGINT)
        launcher.wait(timeout=20)
        if launcher.returncode:
            print(launcher_log.read_text())


def main():
    os.environ['ROS_DOMAIN_ID'] = str(100 + secrets.randbelow(100))
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    rclpy.init(args=[])
    node = Fixture(float(sys.argv[1]), [int(arg) for arg in sys.argv[2:]])
    try:
        with TemporaryDirectory(prefix='grip-smoke-') as temporary:
            run_test(node, Path(temporary))
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
