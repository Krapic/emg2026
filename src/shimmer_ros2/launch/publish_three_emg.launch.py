"""Publish the three working laboratory Shimmers in separate namespaces."""

from launch import LaunchDescription
from launch.actions import TimerAction
from launch_ros.actions import Node


def generate_launch_description():
    # Stagger Bluetooth initialization and internal zeroing.
    return LaunchDescription([
        TimerAction(
            period=float(port * 20),
            actions=[Node(
                package='shimmer_ros2',
                executable='shimmer_publisher',
                name='emg_publisher',
                namespace=f'shimmer{port + 1}',
                parameters=[{'rfcomm_port_num': port}],
                output='screen',
            )],
        )
        for port in range(3)
    ])
