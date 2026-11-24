"""Apply a saved grip model to processed EMG streams."""

from collections import deque
import json
from pathlib import Path

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

from emg_grip_interfaces.msg import Emg, GripForce
from emg_grip_interfaces.srv import LoadGripModel
from shimmer_ros2.grip_data import NS, delayed_emg, feature_names, predict


class GripEstimator(Node):
    def __init__(self):
        super().__init__('grip_estimator')
        self.topics = self.declare_parameter(
            'emg_topics', ['/shimmer1/emg_processed', '/shimmer2/emg_processed']).value
        self.rate = self.declare_parameter('output_hz', 200.0).value
        self.emg_hz = self.declare_parameter('expected_emg_hz', 992.96969699).value
        gap_ms = self.declare_parameter('max_emg_gap_ms', 20.0).value
        if (not self.topics or len(set(self.topics)) != len(self.topics)
                or not np.isfinite(self.rate) or not 0 < self.rate <= 1000
                or not np.isfinite(gap_ms) or not 0 < gap_ms <= 1000):
            raise ValueError('Provjerite topice, frekvenciju i maksimalni EMG razmak.')
        self.period_ns = round(NS / self.rate)
        self.gap_ns = round(gap_ms * 1e6)
        self.model = None
        self.buffers = {topic: deque(maxlen=6000) for topic in self.topics}
        self.last_stamp = 0
        self.publisher = self.create_publisher(GripForce, 'grip_force_estimated', 1024)
        for topic in self.topics:
            self.create_subscription(Emg, topic, lambda msg, key=topic: self.receive(key, msg),
                                     2048)
        self.create_service(LoadGripModel, 'load_grip_model', self.load_model)
        self.create_timer(0.05, self.estimate)

    def load_model(self, request, response):
        try:
            path = Path(request.model_path).expanduser()
            data = json.loads(path.read_text(encoding='utf-8'))
            if (data['version'], data['kind'], data['output']) != (2, 'ridge', 'grip_force_n'):
                raise ValueError('Nepodržan format modela. Ponovno trenirajte model iz snimki.')
            if data['features'] != feature_names(self.topics):
                raise ValueError('Model očekuje drugi redoslijed ili skup EMG kanala.')
            delays = data['emg_delays_ms']
            if (not isinstance(delays, list) or not delays or delays[0] != 0
                    or any(type(delay) is not int or not 0 <= delay <= 1000 for delay in delays)
                    or delays != sorted(set(delays))):
                raise ValueError('Nevaljane EMG odgode modela.')
            model_hz = data.get('emg_hz', [992.96969699] * len(self.topics))
            if (not isinstance(model_hz, list) or len(model_hz) != len(self.topics)
                    or not np.allclose(np.asarray(model_hz, dtype=float), self.emg_hz, atol=0.01)):
                raise ValueError('EMG frekvencija modela ne odgovara postavkama mjerenja.')
            frames = {}
            for topic in self.topics:
                frame = data['frame_ids'][topic]
                if (not isinstance(frame, list) or len(frame) != 1
                        or not isinstance(frame[0], str) or not frame[0]):
                    raise ValueError(f'Model nema jednoznačan frame_id za {topic}.')
                frames[topic] = frame[0]
            mean, scale, coefficients = [np.asarray(data[key], dtype=float)
                                         for key in ('mean', 'scale', 'coefficients')]
            intercept = float(data['intercept'])
            size = len(delays) * len(self.topics)
            if (any(array.shape != (size,) or not np.isfinite(array).all()
                    for array in (mean, scale, coefficients))
                    or np.any(scale <= 0) or not np.isfinite(intercept)):
                raise ValueError('Nevaljani parametri regresije.')
        except (OSError, ValueError, TypeError, KeyError, OverflowError) as error:
            response.message = str(error)
            return response
        self.model = (frames, delays, mean, scale, intercept, coefficients)
        for buffer in self.buffers.values():
            buffer.clear()
        self.last_stamp = self.get_clock().now().nanoseconds
        response.success = True
        response.message = f'Model aktiviran: {path}'
        self.get_logger().info(response.message)
        return response

    def receive(self, topic, msg):
        if self.model is None:
            return
        buffer = self.buffers[topic]
        if msg.header.frame_id != self.model[0][topic]:
            buffer.clear()
            self.get_logger().warning(f'{topic}: frame_id ne odgovara modelu.',
                                      throttle_duration_sec=5.0)
            return
        stamp = msg.header.stamp.sec * NS + msg.header.stamp.nanosec
        if stamp > 0 and (not buffer or stamp > buffer[-1][0]):
            buffer.append((stamp, msg.emg_ch1))

    def estimate(self):
        if self.model is None:
            return
        now = self.get_clock().now().nanoseconds
        oldest = now - 2 * NS
        for buffer in self.buffers.values():
            while buffer and buffer[0][0] < oldest:
                buffer.popleft()
            if not buffer:
                return
        _, delays, *regression = self.model
        history_ns = delays[-1] * 1_000_000
        start = max(self.last_stamp + 1, max(buf[0][0] for buf in self.buffers.values()) + history_ns)
        end = min(now, *(buf[-1][0] for buf in self.buffers.values()))
        start = ((start + self.period_ns - 1) // self.period_ns) * self.period_ns
        if start > end:
            return
        times = np.arange(start, end + 1, self.period_ns, dtype=np.int64)
        streams = []
        for buffer in self.buffers.values():
            stamps = np.fromiter((row[0] for row in buffer), dtype=np.int64, count=len(buffer))
            values = np.fromiter((row[1] for row in buffer), dtype=float, count=len(buffer))
            streams.append((stamps, values[:, None]))
        design, valid = delayed_emg(times, streams, delays, self.gap_ns)
        self.last_stamp = int(times[-1])
        predictions = predict(design[valid], *regression)
        for stamp, value in zip(times[valid], predictions):
            if not np.isfinite(value) or abs(value) > np.finfo(np.float32).max:
                continue
            msg = GripForce()
            msg.header.stamp.sec, msg.header.stamp.nanosec = divmod(int(stamp), NS)
            msg.header.frame_id = 'grip_estimated'
            msg.grip_force = float(value)
            self.publisher.publish(msg)


def main():
    rclpy.init()
    node = None
    try:
        node = GripEstimator()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.try_shutdown()
