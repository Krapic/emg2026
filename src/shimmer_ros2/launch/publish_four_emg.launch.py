"""Publish four Shimmers on separate ports and namespaces."""

from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    # RFCOMM mappings: 4C91 -> 0/ch1, 9D2C -> 1/ch6,
    #                  4C87 -> 2/ch1, 9D23 -> 3/ch6.
    return LaunchDescription([
        Node(
            package='shimmer_ros2',
            executable='shimmer_publisher',
            name='emg_publisher',
            namespace=f'shimmer{port + 1}',
            parameters=[{'rfcomm_port_num': port}],
            output='screen',
        )
        for port in range(4)
    ])
