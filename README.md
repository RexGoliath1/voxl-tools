# voxl-tools

Scripts and param profiles for VOXL2 / ModalAI drone configuration.

## Workflow: transfer and apply a param profile

```
# 1. On Mac — push the profile to the drone
scp params/brecourt_vio.params root@<DRONE_IP>:/tmp/

# 2. Also push the apply script
scp apply_params root@<DRONE_IP>:/tmp/

# 3. SSH into drone and apply
ssh root@<DRONE_IP>
python3 /tmp/apply_params /tmp/brecourt_vio.params

# 4. (Optional) dry-run first to preview what will be set
python3 /tmp/apply_params /tmp/brecourt_vio.params --dry-run
```

## Workflow: capture a full param dump from a reference drone

```bash
# On drone
px4-param show > /tmp/dump.params

# On Mac — pull it
scp root@<DRONE_IP>:/tmp/dump.params .
```

`px4-param show` output is not QGC format — it looks like:
```
x + EKF2_EV_CTRL [294,573] : 15
```

Use it as a human-readable reference to build or verify a profile file. The
`.params` profile files in `params/` use the standard QGC tab-separated format
that `apply_params` parses.

## Param profiles

| File | Description |
|------|-------------|
| `params/brecourt_vio.params` | VIO-primary indoor config (Brecourt production) |

## VOXL utility scripts

Small helper scripts live in `utilities/`.

### Flash ModalAI PX4 base params for the detected vehicle

Run `utilities/voxl-flash-px4-params` from this checkout on your Mac/Linux host
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

## Lessons learned

### `px4-param` is a VOXL binary, not a standard PX4 tool

`px4-param show` and `px4-param set` are installed by the `voxl-px4` package.
Standard PX4 parameter tools (`px4-param` in the NuttX shell, or `pyserial`
over MAVLink) are different. To read parameters without QGC:

```bash
px4-param show              # dump all parameters
px4-param show EKF2_EV_CTRL # show one
px4-param set EKF2_EV_CTRL 15
```

`voxl-configure-px4-params` is a writer, not a reader — it expects a `.params`
or `.cal` file as input. Don't confuse it with `px4-param`.

### Use `scp`, not `rsync`, for file transfer to/from VOXL2

macOS ships `rsync` 2.6.9 (2006), which is incompatible with the newer rsync on
OE Linux. It exits with error 11 / "unexpected end of file". Use `scp` instead:

```bash
# Copy file to drone
scp file.txt root@<IP>:/tmp/

# Copy directory to drone
scp -r local_dir/ root@<IP>:/data/

# Pull from drone
scp root@<IP>:/tmp/file.txt .
```

### `systemctl enable` is required after `dpkg -i`

Installing a `.deb` on VOXL2 does NOT automatically enable the service. After
installing or upgrading any `voxl-*` service package:

```bash
systemctl enable voxl-<service>
systemctl start voxl-<service>
```

Verify:
```bash
systemctl is-active voxl-<service>
journalctl -u voxl-<service> -n 50
```

### DISTANCE_SENSOR data path on VOXL2

`qrb5165-rangefinder-server` (VL53L1X, I2C bus 4) publishes `DISTANCE_SENSOR`
MAVLink messages **directly to PX4** via UDP — it does not go through
`voxl-mavlink-server`. The key config field is `id_for_mavlink: 0` in
`/etc/modalai/qrb5165-rangefinder-server.conf`.

`voxl-mavlink-server` handles the general MPA ↔ MAVLink bridge; the
rangefinder is a separate direct path.

### Verify the VIO profile params

```bash
px4-param show | grep -E 'EKF2_EV_CTRL|EKF2_GPS_CTRL|EKF2_HGT_REF|EKF2_BARO_CTRL|EKF2_OF_CTRL|EKF2_EV_QMIN|EKF2_RNG_CTRL|EKF2_MAG_TYPE|SYS_HAS_GPS|SYS_HAS_MAG'
```

`+` in the output means the value differs from the firmware default and has been saved to flash. Params at their firmware default show no `+` — that's expected.

### GCS connectivity — `voxl-mavlink-server`

MAVLink UDP to GCS is configured in `/etc/modalai/voxl-mavlink-server.conf`.
The field `secondary_static_gcs_ip` sets a static push target (e.g., Mac's IP
on the LAN). Update it when the Mac's IP changes (DHCP):

```bash
# From this repo on macOS or Linux, with the Starling connected over adb:
./set_mavlink_gcs

# If autodetect chooses the wrong interface/IP:
./set_mavlink_gcs --interface en0
./set_mavlink_gcs --ip 192.168.1.104

# Optional SSH mode when you already know the drone IP:
./set_mavlink_gcs --ssh 192.168.1.42

# Also verify inbound MAVLink UDP before opening QGC:
./set_mavlink_gcs --ssh 192.168.1.42 --check-udp

# If working with an older setup that uses the primary slot:
./set_mavlink_gcs --primary

# If the config is already set, run only the UDP smoke test:
./check_mavlink_udp
```

The script backs up the remote config, writes the selected field, and runs
`systemctl restart voxl-mavlink-server`. Default transport is adb. Passing
`--ssh`, `--host`, or `--drone-ip` switches to SSH mode with the default VOXL login
`root` / `oelinux123`; SSH password mode requires `sshpass`, while SSH keys can
be used with `--password ''`. Passing `--check-udp` listens briefly on UDP
`14550` after the restart, so run it before opening QGC.

Manual equivalent:

```bash
# Replace old IP with new IP
sed -i 's/"secondary_static_gcs_ip":.*"OLD"/"secondary_static_gcs_ip":\t"NEW"/' \
    /etc/modalai/voxl-mavlink-server.conf

systemctl restart voxl-mavlink-server
```

QGC default listen port is `14550`.

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
