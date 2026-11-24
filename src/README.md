# Podrijetlo paketa

Tri ROS 2 paketa u ovoj mapi preuzeta su iz javnih repozitorija autora Tomislava Bazine (`tbazina`) i izmijenjena za ovaj projekt. Sva tri su pod licencom Apache-2.0; izvorna datoteka `LICENSE` ostala je u svakom paketu.

| Paket | Izvor | Preuzeta verzija |
|---|---|---|
| `emg_grip_interfaces` | <https://github.com/tbazina/emg_grip_interfaces> | `88ad1c6` |
| `godirect_ros2` | <https://github.com/tbazina/godirect_ros2> | `e86292a` |
| `shimmer_ros2` | <https://github.com/tbazina/shimmer_ros2> | `1323c99` |

Povijest izvornih repozitorija nije prenesena. Za usporedbu s izvornikom kloniraj izvorni repozitorij, prijeđi na navedenu verziju i usporedi ga s mapom paketa.

## Što je izmijenjeno

### emg_grip_interfaces

- Izmijenjeno: `CMakeLists.txt`, `README.md`.
- Dodano: `srv/RecordGrip.srv`, `srv/TrainGrip.srv`, `srv/LoadGripModel.srv`.

### godirect_ros2

- Izmijenjeno: `README.md`.
- Dodano: `config/plotjuggler_three_shimmers_config.xml`, `config/plotjuggler_four_shimmers_config.xml`.

### shimmer_ros2

- Izmijenjeno: `README.md`, `package.xml`, `setup.py`, `scripts/bind_shimmer_to_rfcomm.sh`, `shimmer_ros2/nodes/emg_processor.py`, `shimmer_ros2/nodes/shimmer_publisher.py`, `shimmer_ros2/shimmer_api/emg.py`.
- Dodano u `launch/`: `grip_services.launch.py`, `publish_three_emg.launch.py`, `publish_four_emg.launch.py`.
- Dodano u `shimmer_ros2/`: `grip_data.py`, `grip_report.py`, `nodes/grip_services.py`, `nodes/grip_estimator.py`, `shimmer_api/framing.py`.
- Dodano u `test/`: `test_framing.py`, `test_grip_data.py`, `test_grip_report.py`.
