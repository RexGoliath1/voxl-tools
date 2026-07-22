# voxl-tools

Small command-line utilities for VOXL2 / ModalAI drone setup from a computer or
directly on the VOXL.

## Param profiles

| File | Description |
|------|-------------|
| `params/brecourt_vio.params` | QGC-format VIO-primary indoor config reference (Brecourt production) |

## VOXL utility scripts

Small helper scripts live in `utilities/`.

### Set the VOXL MAVLink GCS IP

`set_mavlink_gcs` updates `voxl-mavlink-server` so the VOXL pushes MAVLink UDP
to this computer. It backs up the remote config, writes the selected static GCS
IP field, and restarts `voxl-mavlink-server` unless `--no-restart` is supplied.
Default transport is adb. Passing `--ssh`, `--host`, or `--drone-ip` uses SSH
with the default VOXL login `root` / `oelinux123`.

```bash
# Auto-detect this computer's route IP and update over adb
./set_mavlink_gcs

# Set an explicit computer IP
./set_mavlink_gcs --ip 192.168.1.104

# Pick the IP from a specific network interface
./set_mavlink_gcs --interface tailscale0
./set_mavlink_gcs --interface en0

# Use SSH when the VOXL is reachable by IP
./set_mavlink_gcs --ssh 192.168.1.42

# Restart and then listen briefly for inbound MAVLink UDP
./set_mavlink_gcs --ssh 192.168.1.42 --check-udp

# Use the primary static GCS field instead of the secondary field
./set_mavlink_gcs --primary

# Preview the config change without writing it
./set_mavlink_gcs --dry-run
```

QGC default listen port is `14550`. Run `--check-udp` before opening QGC, since
only one process can bind the same local UDP port directly.

### Check inbound MAVLink UDP

`check_mavlink_udp` listens for MAVLink packets on the selected local UDP port.

```bash
./check_mavlink_udp
./check_mavlink_udp --port 14550 --timeout 15
```

### Flash ModalAI PX4 base params for the detected vehicle

Run `utilities/voxl-flash-px4-params` from this checkout on your computer
or directly on the VOXL. By default it auto-selects a transport: `--host` uses
SSH, running on a VOXL uses local execution, otherwise it uses an attached adb
device. It reads `/data/modalai/sku.txt` first, then falls back to
`voxl-platform`. For Starling 2 Max, the PX4 parameter platform is `MRB-D0012`;
`M0054` is the VOXL 2 hardware platform.

```bash
# Preview what would be applied over adb
python3 utilities/voxl-flash-px4-params --dry-run

# Apply detected params over adb, preserving existing PX4 calibration files
python3 utilities/voxl-flash-px4-params

# Non-interactive detected load over adb
python3 utilities/voxl-flash-px4-params --yes

# Use SSH/IP instead of adb
python3 utilities/voxl-flash-px4-params --host 192.168.1.57

# Run directly on a VOXL
python3 utilities/voxl-flash-px4-params --transport local

# Force a specific platform or params bundle only when needed
python3 utilities/voxl-flash-px4-params --platform MRB-D0012 --version v1.14 --yes
```

The script wraps ModalAI's `voxl-configure-px4-params -n -p <platform> -v
<version>`. The version is the installed ModalAI PX4 parameter bundle directory
such as `/usr/share/modalai/px4_params/v1.14`, not the VOXL hardware platform.
By default the script chooses the newest installed params version that contains
the detected vehicle file; pass `--version` only to override that choice.

### Restart common VOXL services

Run `utilities/voxl-restart-services` from this checkout or directly on the
VOXL. It uses the same transport behavior as the PX4 param helper: adb by
default when a device is attached, `--host` for SSH, or `--transport local` on
the VOXL. With no service names it shows a numbered menu. It also accepts short
aliases:

```bash
# Menu selection over adb
python3 utilities/voxl-restart-services

# Restart camera server and MAVLink server over adb
python3 utilities/voxl-restart-services camera mavlink

# Use SSH/IP instead of adb
python3 utilities/voxl-restart-services --host 192.168.1.57 camera mavlink

# Show common/discovered VOXL services and current state
python3 utilities/voxl-restart-services --list

# Preview restart commands
python3 utilities/voxl-restart-services camera mavlink --dry-run
```

Common aliases include `camera`, `mavlink`, `vision`, `openvins`, `qvio`, `imu`,
`rangefinder`, `tflite`, `portal`, `px4`, `streamer`, and `mavcam`.

### Survey VOXL link dropouts

Run `utilities/voxl-link-survey` from the computer to log timestamped LAN, SSH,
and optional MAVLink reachability while testing router placement, antennas, or
QGC dropouts:

```bash
# Ping the VOXL and gateway every 2 seconds for 5 minutes
utilities/voxl-link-survey 192.168.0.155 --gateway 192.168.0.1 --duration 300

# Include short SSH checks and write a CSV
utilities/voxl-link-survey 192.168.0.155 --gateway 192.168.0.1 \
    --ssh-check --duration 300 --csv logs/voxl-link.csv

# Also watch local QGC MAVLink UDP and count only packets sourced by this VOXL
utilities/voxl-link-survey 192.168.0.155 --gateway 192.168.0.1 \
    --ssh-check --mavlink-port 14550 --mavlink-source 192.168.0.155
```

If gateway ping stays healthy while VOXL ping/SSH fails, focus on the VOXL/AP
wireless link or the VOXL itself. If the gateway also drops, focus on the
computer interface, router bridge, or upstream LAN.

### Pull VOXL logs

If the Brecourt TFLite ROS Docker run wrote logs to a Starling path, a
host-user path, or if the Docker container still exists, pull ROS logs over adb
or SSH/SCP. The same command also pulls PX4 ULog files from `/data/px4/log`
when that directory exists:

```bash
./pull_voxl_logs
```

Default output:

```text
logs/<vehicle id>/ros/<ROS datetime log directories>
logs/<vehicle id>/terminal/<run.sh terminal logs>
logs/<vehicle id>/px4/<PX4 date directories and .ulg files>
```

The vehicle id is derived from remote VOXL identity such as hostname,
`/data/modalai/sku.txt`, `voxl-platform`, `MAV_SYS_ID`, and machine-id. Repeated
pulls for the same vehicle update the same local directory instead of creating
timestamped snapshots.

The default `auto` source checks Starling paths such as `/home/root` and
`/data`, then host-user paths under `$HOME`, then falls back to copying from a
`brecourt-ros2` Docker container. When it finds `brecourt/log/ros`, it also
pulls sibling `brecourt/log/terminal` logs from `run.sh`. Useful overrides:

```bash
./pull_voxl_logs --serial d6da8cd6
./pull_voxl_logs --scp 192.168.1.57
./pull_voxl_logs --source starling
./pull_voxl_logs --source host --remote-repo-dir '$HOME/git/Brecourt/brecourt_tflite_tracker'
./pull_voxl_logs --source docker
./pull_voxl_logs --px4-log-dir /data/px4/log/2026-07-14
./pull_voxl_logs --no-px4-logs
```
