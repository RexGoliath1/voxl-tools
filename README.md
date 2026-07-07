# voxl-tools

Scripts and param profiles for VOXL2 / ModalAI drone configuration.

## Workflow: transfer and apply a param profile

```
# 1. On Mac — push the profile to the drone
scp params/brecourt_vio.params root@<DRONE_IP>:/tmp/

# 2. Also push the apply script
scp apply_params.py root@<DRONE_IP>:/tmp/

# 3. SSH into drone and apply
ssh root@<DRONE_IP>
python3 /tmp/apply_params.py /tmp/brecourt_vio.params

# 4. (Optional) dry-run first to preview what will be set
python3 /tmp/apply_params.py /tmp/brecourt_vio.params --dry-run
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
that `apply_params.py` parses.

## Param profiles

| File | Description |
|------|-------------|
| `params/brecourt_vio.params` | VIO-primary indoor config (Brecourt production) |

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
./set_mavlink_gcs.py

# If autodetect chooses the wrong interface/IP:
./set_mavlink_gcs.py --interface en0
./set_mavlink_gcs.py --ip 192.168.1.104

# Optional SSH mode when you already know the drone IP:
./set_mavlink_gcs.py --drone-ip 192.168.1.42

# If working with an older setup that uses the primary slot:
./set_mavlink_gcs.py --primary
```

The script backs up the remote config, writes the selected field, and runs
`systemctl restart voxl-mavlink-server`. Default transport is adb. Passing
`--drone-ip` switches to SSH mode with the default VOXL login
`root` / `oelinux123`; SSH password mode requires `sshpass`, while SSH keys can
be used with `--password ''`.

Manual equivalent:

```bash
# Replace old IP with new IP
sed -i 's/"secondary_static_gcs_ip":.*"OLD"/"secondary_static_gcs_ip":\t"NEW"/' \
    /etc/modalai/voxl-mavlink-server.conf

systemctl restart voxl-mavlink-server
```

QGC default listen port is `14550`.

### Pull Brecourt ROS logs from VOXL Docker

If the Brecourt ROS Docker run wrote logs to a host-mounted volume, or if the
Docker container still exists, pull ROS logs over SSH/SCP:

```bash
./pull_ros_logs.sh root@192.168.1.57
```

Default output:

```text
ros_logs/root_192.168.1.57/<ROS datetime log directories>
```

The default `auto` source first looks for saved host logs such as
`*/brecourt/log/ros`, then falls back to copying from a `brecourt-ros2` Docker
container. Useful overrides:

```bash
./pull_ros_logs.sh --source docker root@192.168.1.57
./pull_ros_logs.sh --source host --remote-repo-dir /data/brecourt_tflite_tracker root@192.168.1.57
./pull_ros_logs.sh --host-log-dir /root/brecourt/log/ros root@192.168.1.57
```
