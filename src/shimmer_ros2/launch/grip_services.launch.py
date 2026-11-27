"""Start processing, recording, training and live estimation."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import yaml


def start_nodes(context):
    namespaces = LaunchConfiguration('shimmers').perform(context).split()
    if not namespaces or len(set(namespaces)) != len(namespaces):
        raise ValueError('Provide a space-separated list of distinct Shimmer namespaces.')
    data_dir = LaunchConfiguration('data_dir')
    config = Path(get_package_share_directory('shimmer_ros2')) / 'config/shimmer_config.yaml'
    with config.open(encoding='utf-8') as stream:
        settings = yaml.safe_load(stream)['emg_processor']['ros__parameters']
    # Humble cannot pass an empty array as a launch dictionary parameter.
    # A zero-width stop band is equivalent here: the high-pass removes DC.
    if not settings['band_stop']:
        settings['band_stop'] = [0.0, 0.0]
    settings['queue_size'] = 2048
    settings['sampling_rate'] = float(LaunchConfiguration('emg_hz').perform(context))
    processors = [Node(package='shimmer_ros2', executable='emg_processor', namespace=name,
                       parameters=[settings], output='screen') for name in namespaces]
    if LaunchConfiguration('processors_only').perform(context) == 'true':
        return processors
    topics = [f'/{name}/emg_processed' for name in namespaces]
    estimator = Node(package='shimmer_ros2', executable='grip_estimator', output='screen',
                     parameters=[{'emg_topics': topics,
                                  'expected_emg_hz': settings['sampling_rate'],
                                  'prediction_horizon_ms': float(LaunchConfiguration(
                                      'prediction_horizon_ms').perform(context))}])
    if LaunchConfiguration('estimation_only').perform(context) == 'true':
        return [*processors, estimator]
    return [
        *processors,
        Node(package='shimmer_ros2', executable='grip_recorder', output='screen',
             parameters=[{'data_dir': data_dir,
                          'emg_topics': topics, 'record_raw_emg': True,
                          'expected_emg_hz': settings['sampling_rate']}]),
        Node(package='shimmer_ros2', executable='grip_trainer', output='screen',
             parameters=[{'data_dir': data_dir}]),
        estimator,
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('shimmers', default_value='shimmer1 shimmer2'),
        DeclareLaunchArgument('emg_hz', default_value='992.96969699'),
        DeclareLaunchArgument('processors_only', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('estimation_only', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('prediction_horizon_ms', default_value='500.0'),
        DeclareLaunchArgument('data_dir', default_value=str(Path.home() / 'emg2026' / 'grip_data')),
        OpaqueFunction(function=start_nodes),
    ])
