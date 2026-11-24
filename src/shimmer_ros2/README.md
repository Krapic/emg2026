# shimmer_ros2

A ROS 2 interface for Shimmer3 EMG sensors. Data can be streamed from multiple Shimmer sensors simultaneously. Each sample is stamped with the ROS node clock at the first received sample plus the elapsed ticks of the internal Shimmer 32 kHz timer.

In the `emg2026` workspace the usual entry point is `./pokreni.sh` in the workspace root. It pairs and binds the laboratory devices, starts the nodes of this package at 512 Hz and offers the recording, training and estimation commands. See `POKRETANJE.md` and `SNIMANJE_I_MODEL.md` there. The sections below describe the package on its own.

## Prerequisites
- Turn on your Shimmer3 sensor(s) and ensure they are discoverable via Bluetooth.
- Add your user to the `dialout` group:

```bash
sudo usermod -aG dialout $USER
```

## Binding Shimmer sensors to RFCOMM

1. Find the MAC addresses of your Shimmer devices:

```bash
hcitool scan
```

2. Run the binding script as root, providing all Shimmer MAC addresses as positional arguments:

```bash
sudo ros2 run shimmer_ros2 bind_shimmer_to_rfcomm.sh <MAC1> [<MAC2> ...]
```

## Streaming EMG data

1. Edit the Shimmer configuration in `config/shimmer_config.yaml`.
2. Launch the EMG publisher:

```bash
ros2 launch shimmer_ros2 publish_emg.launch.py
```

3. Process EMG signal:

```bash
ros2 launch shimmer_ros2 process_emg.launch.py
```

## Four laboratory Shimmers

For the three-device setup (4C91, 9D2C and 4C87), use:

```bash
ros2 launch shimmer_ros2 publish_three_emg.launch.py
```

This starts publishers at 0, 20 and 40 seconds, using the default acquisition
and zeroing settings. Stop any existing publishers on these ports first. The
9D23 device is excluded: it has not produced a valid EMG stream during the
connection diagnostics. The four-device launch below is available for later
use once that device has been repaired or configured successfully.

The tested port mapping is:

| Namespace | Bluetooth address | Port | RFCOMM channel |
|---|---|---|---|
| `/shimmer1` | `00:06:66:B1:4C:91` | `/dev/rfcomm0` | 1 |
| `/shimmer2` | `60:8A:10:40:9D:2C` | `/dev/rfcomm1` | 6 |
| `/shimmer3` | `00:06:66:B1:4C:87` | `/dev/rfcomm2` | 1 |
| `/shimmer4` | `60:8A:10:40:9D:23` | `/dev/rfcomm3` | 6 |

Pair and trust each device first using `bluetoothctl` (standard Shimmer3 PIN:
`1234`). RFCOMM binding alone does not pair a sensor. With the publishers
stopped, bind unused ports using explicit channels:

```bash
sudo rfcomm bind 0 00:06:66:B1:4C:91 1
sudo rfcomm bind 1 60:8A:10:40:9D:2C 6
sudo rfcomm bind 2 00:06:66:B1:4C:87 1
sudo rfcomm bind 3 60:8A:10:40:9D:23 6
```

For an existing incorrect binding, first run `sudo rfcomm release <port_number>`
after stopping the publisher for that port. The older binding script assumes
channel 1 and is therefore unsuitable for this complete set. Determine the
channel of other sensors with `sdptool browse <MAC>`.

Build and launch all four publishers from the workspace root (do not also run
individual publishers on these same ports):

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select shimmer_ros2 --symlink-install
source install/setup.bash
ros2 launch shimmer_ros2 publish_four_emg.launch.py
```

The launch uses the publisher's default settings, including approximately
993 Hz, gain 12 and four seconds of internal test-signal zeroing. Each raw
two-channel stream has its own topic `/shimmerN/emg_stream`. It does not start
signal processing. In another sourced terminal in the workspace root, check
received samples with:

```bash
python3 check_shimmers.py
```

This observes ten seconds and prints counts and rates derived from source
timestamps; it does not validate electrode contact or signal quality.

## Grip force recording, training and estimation

One launch file starts an EMG processor for each Shimmer namespace together
with the three grip nodes. The raw EMG publishers and the dynamometer must
already be running.

```bash
ros2 launch shimmer_ros2 grip_services.launch.py \
  shimmers:="shimmer1" emg_hz:=512.0 data_dir:=/path/to/grip_data
```

| Argument | Default | Meaning |
|---|---|---|
| `shimmers` | `shimmer1 shimmer2` | Space-separated Shimmer namespaces. |
| `emg_hz` | `992.96969699` | Sampling rate of the running EMG publishers. |
| `data_dir` | `~/emg2026/grip_data` | Where recordings and models are stored. |
| `processors_only` | `false` | Start only the EMG processors. |
| `estimation_only` | `false` | Start the processors and the estimator, without recorder and trainer. |

These defaults differ from `./pokreni.sh`, which uses one Shimmer at 512 Hz and
the `grip_data` folder of the workspace. Pass the arguments explicitly when
launching by hand.

| Node | Interface | Purpose |
|---|---|---|
| `grip_recorder` | service `/record_grip` (`RecordGrip`), topic `/grip_force_target` | Records raw and processed EMG with the measured force for 20 to 35 s, guided through 100, 75, 50 and 25 % MVC or free, and saves the streams, the aligned table and metadata. |
| `grip_trainer` | service `/train_grip_model` (`TrainGrip`) | Fits a ridge regression on the first EMG channel at delays of 0 to 500 ms and saves it as JSON with training and validation error. |
| `grip_estimator` | service `/load_grip_model` (`LoadGripModel`), topic `/grip_force_estimated` | Applies a loaded model to processed EMG and publishes the estimated force at 200 Hz. |

```bash
ros2 service call /record_grip emg_grip_interfaces/srv/RecordGrip \
  "{session: P01_pokus1, duration_sec: 30.0, guided: true, mvc_n: 250.0}"
ros2 service call /train_grip_model emg_grip_interfaces/srv/TrainGrip \
  "{training_ids: [RECORDING_ID], validation_ids: [RECORDING_ID]}"
ros2 service call /load_grip_model emg_grip_interfaces/srv/LoadGripModel \
  "{model_path: /path/to/grip_data/models/MODEL_ID.json}"
```

The services take full recording IDs and return no warning about the content
of a recording. Session labels and the report on held force and error by force
level come from `./pokreni.sh` and `scripts/analiza.py` in the workspace.

`shimmer_ros2/grip_data.py` holds the alignment, delayed features and
regression shared by the trainer and the estimator. `shimmer_ros2/grip_report.py`
holds the checks of recordings and models. Both need only NumPy, so their tests
run without ROS from this package's folder:

```bash
python3 -m pytest test/test_grip_data.py test/test_grip_report.py
```

## Visualizing data

`./pokreni.sh` opens PlotJuggler with a layout generated for the selected
Shimmers. To open it by hand, use the launch file of `godirect_ros2` with one
of the layouts in its `config` folder:

```bash
ros2 launch godirect_ros2 plotjuggler_godirect.launch.py \
  layout_file:=/path/to/plotjuggler_four_shimmers_config.xml
```

The `.launch` files in the `launch` folder are left from the ROS 1 package and
are not installed.
