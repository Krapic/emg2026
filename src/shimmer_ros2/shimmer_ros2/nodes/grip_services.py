"""ROS 2 services for recording aligned EMG/force and fitting a force estimator."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import time
from uuid import uuid4

import numpy as np
import rclpy
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup, ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node

from emg_grip_interfaces.msg import Emg, GripForce
from emg_grip_interfaces.srv import RecordGrip, TrainGrip
from shimmer_ros2.grip_data import (
    EMG_DELAYS_MS, MAX_EMG_GAP_NS, NS, align, delayed_emg, feature_names,
    fit_model, load_recording, metrics, predict,
    summarize, write_csv, write_json,
)

DEFAULT_TOPICS = ['/shimmer1/emg_processed', '/shimmer2/emg_processed']
DEFAULT_DIRECTORY = str(Path.home() / 'emg2026' / 'grip_data')


class GripRecorder(Node):
    def __init__(self):
        super().__init__('grip_recorder')
        self.root = Path(self.declare_parameter('data_dir', DEFAULT_DIRECTORY).value).expanduser()
        emg_topics = self.declare_parameter('emg_topics', DEFAULT_TOPICS).value
        force_topic = self.declare_parameter('force_topic', '/grip_force_stream').value
        emg_hz = self.declare_parameter('expected_emg_hz', 992.96969699).value
        force_hz = self.declare_parameter('expected_force_hz', 200.0).value
        gap_ms = self.declare_parameter('max_emg_gap_ms', 20.0).value
        if (not emg_topics or len(set(emg_topics + [force_topic])) != len(emg_topics) + 1
                or not all(topic.startswith('/') for topic in emg_topics + [force_topic])
                or not all(np.isfinite(v) and v > 0 for v in (emg_hz, force_hz, gap_ms))):
            raise ValueError('Provjerite topic nazive, očekivane frekvencije i max_emg_gap_ms.')
        self.emg_topics = emg_topics
        self.raw_topics = []
        if self.declare_parameter('record_raw_emg', False).value:
            self.raw_topics = [f"{topic.rsplit('/', 1)[0]}/emg_stream" for topic in emg_topics]
            if len(set(self.raw_topics + emg_topics + [force_topic])) != 2 * len(emg_topics) + 1:
                raise ValueError('Sirovi i obrađeni EMG moraju biti na različitim topicima.')
        self.force_topic = force_topic
        self.expected = {topic: emg_hz for topic in emg_topics + self.raw_topics}
        self.expected[force_topic] = force_hz
        self.max_gap_ns = int(gap_ms * 1e6)
        self.lock = Lock()
        self.record_lock = Lock()
        self.latest = {}
        self.capture = None
        self.capture_window = None
        stream_group = MutuallyExclusiveCallbackGroup()
        service_group = ReentrantCallbackGroup()
        for topic in self.expected:
            kind = GripForce if topic == force_topic else Emg
            self.create_subscription(kind, topic, lambda msg, key=topic: self.receive(key, msg),
                                     2048, callback_group=stream_group)
        self.target_publisher = self.create_publisher(GripForce, 'grip_force_target', 10)
        self.create_service(RecordGrip, 'record_grip', self.record, callback_group=service_group)

    def receive(self, topic, msg):
        stamp = msg.header.stamp.sec * NS + msg.header.stamp.nanosec
        if stamp <= 0:
            return
        received = self.get_clock().now().nanoseconds
        values = (msg.grip_force,) if topic == self.force_topic else (msg.emg_ch1,)
        with self.lock:
            self.latest[topic] = (time.monotonic(), stamp)
            if self.capture is not None and self.capture_window[0] <= stamp < self.capture_window[1]:
                self.capture[topic].append((stamp, received, msg.header.frame_id, *values))

    def record(self, request, response):
        if not self.record_lock.acquire(blocking=False):
            response.message = 'Snimanje je već u tijeku.'
            return response
        try:
            self.record_experiment(request, response)
        except (ValueError, OSError, RuntimeError) as error:
            response.message = str(error)
            self.get_logger().error(response.message)
        finally:
            self.record_lock.release()
        return response

    def record_experiment(self, request, response):
        duration = request.duration_sec or 30.0
        mvc = request.mvc_n
        if not 20 <= duration <= 35 or not request.session.strip():
            raise ValueError('Zadajte oznaku sesije i trajanje između 20 i 35 s.')
        if not np.isfinite(mvc) or not 0 <= mvc <= np.finfo(np.float32).max:
            raise ValueError('MVC mora biti valjana nenegativna vrijednost u N.')
        phases = []
        with self.lock:
            start_ns = self.get_clock().now().nanoseconds
            start = time.monotonic()
            missing = [topic for topic in self.expected
                       if topic not in self.latest
                       or start - self.latest[topic][0] > 2
                       or abs(start_ns - self.latest[topic][1]) > 2 * NS]
            if missing:
                raise ValueError('Nema svježih podataka: ' + ', '.join(missing))
            end_ns = start_ns + round(duration * NS)
            self.capture_window = (start_ns, end_ns)
            streams = self.capture = {topic: [] for topic in self.expected}
        try:
            if request.guided:
                for target in [100, 0, 75, 0, 50, 0, 25, 0]:
                    offset = sum(phase['duration_sec'] for phase in phases)
                    self.sleep_until(start + offset)
                    phase_duration = duration / (5 if target else 20)
                    cue = self.get_clock().now()
                    target_n = mvc * (target / 100) if mvc else None
                    if target_n is not None and phases:
                        self.publish_target(cue - Duration(nanoseconds=1_000_000),
                                            phases[-1]['target_n'])
                    phases.append({
                        'target_percent_mvc': target, 'target_n': target_n,
                        'duration_sec': phase_duration, 'cue_stamp_ns': cue.nanoseconds,
                        'planned_start_ns': start_ns + round(offset * NS),
                        'planned_end_ns': start_ns + round((offset + phase_duration) * NS),
                    })
                    if target_n is not None:
                        self.publish_target(cue, target_n)
                    label = f' ({target_n:g} N)' if target_n is not None else ''
                    self.get_logger().info(f'Cilj stiska: {target}% MVC{label}')
            else:
                self.get_logger().info(f'Snimanje {duration:g} s. Započnite pokušaj.')
            self.sleep_until(start + duration)
            self.get_logger().info('Završeno mjerenje. Otpustite stisak.')
            # The existing FFT processor emits each block after it has been collected.
            self.sleep_until(start + duration + 1.5)
        finally:
            if request.guided and mvc and rclpy.ok():
                self.publish_target(self.get_clock().now(), 0.0)
            with self.lock:
                self.capture = None
                self.capture_window = None

        summaries = {topic: summarize(rows, self.expected[topic]) for topic, rows in streams.items()}
        frame_ids = {topic: sorted({row[2] for row in rows}) for topic, rows in streams.items()}
        if any(len(ids) != 1 or not ids[0] for ids in frame_ids.values()):
            raise ValueError('Identitet izvora promijenio se tijekom snimanja ili nedostaje.')
        times, x, y = align([streams[topic] for topic in self.emg_topics],
                            streams[self.force_topic], self.max_gap_ns)
        # Bound each interval's contribution so gaps cannot inflate coverage.
        max_interval = 3 * NS / self.expected[self.force_topic]
        coverage = float(np.minimum(np.diff(times), max_interval).sum() / NS / duration)
        if len(times) < 50 or coverage < 0.8:
            raise ValueError(f'Nedovoljna pokrivenost poravnatih podataka ({coverage:.1%}).')
        features = feature_names(self.emg_topics)
        model_sources = {topic: frame_ids[topic] for topic in self.emg_topics + [self.force_topic]}
        recording_id = uuid4().hex
        parent = self.root / 'recordings'
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / recording_id
        with TemporaryDirectory(dir=parent, prefix='.recording-') as temporary:
            staging = Path(temporary)
            for index, topic in enumerate(self.emg_topics, 1):
                write_csv(staging / f'emg{index}.csv',
                          ['stamp_ns', 'received_ns', 'frame_id', 'ch1_mv'], streams[topic])
            for index, topic in enumerate(self.raw_topics, 1):
                write_csv(staging / f'raw_emg{index}.csv',
                          ['stamp_ns', 'received_ns', 'frame_id', 'ch1_mv'], streams[topic])
            write_csv(staging / 'force.csv', ['stamp_ns', 'received_ns', 'frame_id', 'force_n'],
                      streams[self.force_topic])
            write_csv(staging / 'aligned.csv', ['stamp_ns', *features, 'force_n'],
                      ((int(t), *values, force) for t, values, force in zip(times, x, y)))
            write_json(staging / 'metadata.json', {
                'version': 1, 'recording_id': recording_id, 'session': request.session.strip(),
                'created_utc': datetime.now(timezone.utc).isoformat(),
                'start_ns': start_ns, 'end_ns': end_ns, 'phases': phases, 'mvc_n': mvc or None,
                'emg_topics': self.emg_topics, 'raw_emg_topics': self.raw_topics,
                'force_topic': self.force_topic,
                'features': features, 'frame_ids': model_sources,
                'raw_frame_ids': {topic: frame_ids[topic] for topic in self.raw_topics},
                'streams': summaries,
                'alignment': 'force_header_stamp_with_bounded_linear_emg_interpolation',
                'timing_basis': 'ROS header timestamps; no hardware synchronization or delay correction',
                'max_emg_gap_ns': self.max_gap_ns, 'aligned_rows': len(times),
                'coverage_fraction': coverage,
            })
            staging.rename(target)
        response.success = True
        response.recording_id = recording_id
        response.directory = str(target)
        response.aligned_rows = len(times)
        response.message = 'Snimka spremljena.'
        self.get_logger().info(f'{response.message} {target} ({len(times)} redaka)')

    def publish_target(self, stamp, target_n):
        msg = GripForce()
        msg.header.stamp = stamp.to_msg()
        msg.header.frame_id = 'grip_target'
        msg.grip_force = target_n
        self.target_publisher.publish(msg)

    @staticmethod
    def sleep_until(deadline):
        while rclpy.ok():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.1))
        raise RuntimeError('Snimanje prekinuto gašenjem ROS-a.')


class GripTrainer(Node):
    def __init__(self):
        super().__init__('grip_trainer')
        self.root = Path(self.declare_parameter('data_dir', DEFAULT_DIRECTORY).value).expanduser()
        self.alpha = self.declare_parameter('ridge_alpha', 1.0).value
        if not np.isfinite(self.alpha) or self.alpha <= 0:
            raise ValueError('ridge_alpha mora biti pozitivan.')
        self.create_service(TrainGrip, 'train_grip_model', self.train)

    def train(self, request, response):
        try:
            self.train_model(request, response)
        except (ValueError, OSError, KeyError, TypeError, np.linalg.LinAlgError) as error:
            response.message = str(error)
            self.get_logger().error(response.message)
        return response

    def train_model(self, request, response):
        ids = list(request.training_ids) + list(request.validation_ids)
        if not request.training_ids or len(set(ids)) != len(ids):
            raise ValueError('Zadajte snimke za učenje. Svaka snimka smije biti navedena samo jednom.')
        recordings = [load_recording(self.root, recording_id) for recording_id in ids]
        schema = recordings[0][0]
        if any(recording[0] != schema for recording in recordings):
            raise ValueError('Snimke moraju imati isti redoslijed značajki, izvore i EMG frekvencije.')
        # Build history separately for each recording.
        designs = []
        for recording_id, (_, times, emg, force) in zip(ids, recordings):
            design, valid = delayed_emg(times, [(times, emg)], EMG_DELAYS_MS, MAX_EMG_GAP_NS)
            if np.count_nonzero(valid) < 50:
                raise ValueError(f'Snimka {recording_id} nema dovoljno neprekinute EMG povijesti.')
            designs.append((design[valid], force[valid]))
        n_train = len(request.training_ids)
        x = np.concatenate([design for design, _ in designs[:n_train]])
        y = np.concatenate([force for _, force in designs[:n_train]])
        mean, scale, intercept, coefficients = fit_model(x, y, self.alpha)
        model = {
            'version': 2, 'kind': 'ridge', 'output': 'grip_force_n',
            'created_utc': datetime.now(timezone.utc).isoformat(),
            'features': schema[0], 'frame_ids': schema[1], 'emg_hz': schema[2], 'alpha': self.alpha,
            'emg_delays_ms': list(EMG_DELAYS_MS),
            'mean': mean.tolist(), 'scale': scale.tolist(), 'intercept': intercept,
            'coefficients': coefficients.tolist(),
            'training_ids': list(request.training_ids), 'validation_ids': list(request.validation_ids),
            'training_rows': len(y), 'validation_rows': 0,
            'training_metrics': metrics(y, predict(x, mean, scale, intercept, coefficients)),
            'validation_metrics': None,
        }
        if request.validation_ids:
            x_val = np.concatenate([design for design, _ in designs[n_train:]])
            y_val = np.concatenate([force for _, force in designs[n_train:]])
            model['validation_rows'] = len(y_val)
            model['validation_metrics'] = metrics(
                y_val, predict(x_val, mean, scale, intercept, coefficients))
        directory = self.root / 'models'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f'{uuid4().hex}.json'
        with TemporaryDirectory(dir=directory, prefix='.model-') as temporary:
            staging = Path(temporary) / path.name
            write_json(staging, model)
            staging.rename(path)
        response.success = True
        response.model_path = str(path)
        response.training_rows = model['training_rows']
        response.validation_rows = model['validation_rows']
        response.message = ('Model spremljen i provjeren na odvojenim snimkama.'
                            if request.validation_ids else 'Model spremljen. Potrebna je odvojena validacija.')


def run_node(node_class):
    rclpy.init()
    node = None
    executor = MultiThreadedExecutor(num_threads=2)
    try:
        node = node_class()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.try_shutdown()
        executor.shutdown()
        if node is not None:
            node.destroy_node()


def record_main():
    run_node(GripRecorder)


def train_main():
    run_node(GripTrainer)
