# emg_grip_interfaces
[![CI](https://github.com/tbazina/emg_grip_interfaces/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tbazina/emg_grip_interfaces/actions/workflows/ci.yml)

This package contains the message and service definitions for the `shimmer_ros2` and `godirect_ros2` ROS2 packages.

## Messages

| Message | Content |
|---|---|
| `Emg` | One EMG sample in mV for channels 1 and 2. The header carries the sample time and the sensor name as `frame_id`. |
| `Fft` | The spectrum of one EMG block for both channels, its frequencies, the signal reconstructed by inverse FFT and the original sample times. |
| `GripForce` | One force sample in N. The header carries the sample time and the measurement type (`grip` or `pinch`) as `frame_id`. |

## Services

| Service | Request | Response |
|---|---|---|
| `CalibrationExperiment` | `request_experiment` | The recorded `data` and their `stamp`. Used by the calibration node of `godirect_ros2`. |
| `RecordGrip` | `session`, `duration_sec`, `guided`, `mvc_n` | `success`, `message`, `recording_id`, `directory`, `aligned_rows` |
| `TrainGrip` | `training_ids`, `validation_ids` | `success`, `message`, `model_path`, `training_rows`, `validation_rows` |
| `LoadGripModel` | `model_path` | `success`, `message` |

The last three are served by the grip nodes of `shimmer_ros2`.
