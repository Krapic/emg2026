"""Observe all four raw EMG topics for ten seconds without changing devices."""

import time

import rclpy
from emg_grip_interfaces.msg import Emg
from rclpy.node import Node


def main():
    rclpy.init()
    node = Node('check_four_shimmers')
    readings = {i: [] for i in range(1, 5)}

    def receive(index, msg):
        readings[index].append((
            msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec,
            msg.header.frame_id,
        ))

    subscriptions = [node.create_subscription(
        Emg, f'/shimmer{i}/emg_stream',
        lambda msg, index=i: receive(index, msg), 2000,
    ) for i in readings]
    try:
        deadline = time.monotonic() + 10
        while rclpy.ok() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
        for index, samples in readings.items():
            elapsed = ((samples[-1][0] - samples[0][0]) / 1e9
                       if len(samples) > 1 else 0)
            rate = (len(samples) - 1) / elapsed if elapsed > 0 else 0
            frame = samples[-1][1] if samples else '-'
            print(f'shimmer{index}: {len(samples)} samples; '
                  f'{rate:.1f} Hz from timestamps; frame_id={frame}')
    finally:
        for subscription in subscriptions:
            node.destroy_subscription(subscription)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
