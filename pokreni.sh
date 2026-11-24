#!/usr/bin/env bash
# ROS uses the system Python and the workspace built for ROS Humble.
set -e
LAB_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f /opt/ros/humble/setup.bash || ! -f "$LAB_ROOT/install/setup.bash" ]]; then
    echo 'Nedostaje ROS Humble ili izgrađen projekt. Izgradite workspace s colcon build --symlink-install.' >&2
    exit 1
fi
source /opt/ros/humble/setup.bash
source "$LAB_ROOT/install/setup.bash"
exec /usr/bin/python3 "$LAB_ROOT/scripts/lab.py" "$@"
