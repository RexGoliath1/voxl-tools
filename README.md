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

### EKF2 VIO parameter reference

Verify the 10 params that define the VIO profile:

```bash
px4-param show | grep -E 'EKF2_EV_CTRL|EKF2_GPS_CTRL|EKF2_HGT_REF|EKF2_BARO_CTRL|EKF2_OF_CTRL|EKF2_EV_QMIN|EKF2_RNG_CTRL|EKF2_MAG_TYPE|SYS_HAS_GPS|SYS_HAS_MAG'
```

#### `EKF2_EV_CTRL` — External Vision fusion bitmask

Controls which data from VIO (e.g. open-vins) is fused into EKF2.

| Bit | Value | Fuses |
|-----|-------|-------|
| 0 | 1 | Horizontal position from EV |
| 1 | 2 | Vertical position from EV |
| 2 | 4 | Velocity from EV |
| 3 | 8 | Yaw from EV |

`15` = all bits set = fuse everything. `0` = VIO ignored entirely.
`3` (bits 0+1) is the minimum useful value: horizontal + vertical position only.

#### `EKF2_GPS_CTRL` — GPS fusion bitmask

Same bitmask structure as EV_CTRL but for GPS. `15` = full GPS fusion (pos,
vel, height, yaw). `0` = GPS completely off. For indoor VIO-only flight this
must be `0` — GPS and VIO will conflict if both are fused simultaneously.

#### `EKF2_HGT_REF` — Primary height reference

Determines what sensor anchors D=0 in the local NED frame.

| Value | Source |
|-------|--------|
| 0 | GPS |
| 1 | Barometer |
| 2 | Rangefinder |
| 3 | EV (VIO) |

Brecourt uses `2` (VL53L1X rangefinder, 3m max range). This means D=0 is
ground level regardless of where VIO initialized — important for the
`target_D` precision landing setpoint to mean what it says.

When the rangefinder exceeds its range (>3m AGL), EKF2 falls back to the next
available sensor. `EKF2_BARO_CTRL = 1` must be set to provide that fallback.

#### `EKF2_BARO_CTRL` — Barometer fusion

`1` = baro measurements fused into EKF2. With `EKF2_HGT_REF = 2`, baro is not
the primary height source but acts as fallback when the rangefinder loses lock.
`0` = baro completely ignored (leaves no height fallback if rangefinder drops).

#### `EKF2_OF_CTRL` — Optical flow fusion

`1` = fuse optical flow velocity measurements. The Starling 2 has a downward
optical flow camera. Optical flow gives horizontal velocity from frame-to-frame
pixel motion + rangefinder altitude, which helps EKF2 when VIO estimates are
noisy or lagged.

#### `EKF2_EV_QMIN` — Minimum EV quality threshold

Range 0–100 (percent). EV measurements below this quality score are rejected.
`1` ≈ accept everything (useful for open-vins which may report low confidence
at startup). `16` (the default) rejects low-confidence VIO data — appropriate
for a well-tuned system but can cause VIO to be ignored during initialization.

#### `EKF2_RNG_CTRL` — Rangefinder control

`0` = rangefinder not used by EKF2. `1` = rangefinder fused as a height source
(complementary to `EKF2_HGT_REF`). Must be `1` when `EKF2_HGT_REF = 2`.

#### `EKF2_MAG_TYPE` — Magnetometer fusion mode

`0` = automatic (use mag when available). `5` = no mag fusion. Indoor flights
disable mag because: (1) VIO provides yaw, (2) indoor magnetic fields are
disturbed by motors, rebar, and electronics. Without a clean mag signal,
fusing it degrades the yaw estimate rather than helping it.

#### `SYS_HAS_GPS` / `SYS_HAS_MAG`

Declares to PX4 whether the hardware has GPS/mag physically present.
Setting to `0` suppresses preflight check failures for missing sensors and
prevents PX4 from waiting for a GPS/mag lock that will never come. These are
capability declarations, not fusion controls — set `EKF2_GPS_CTRL` and
`EKF2_MAG_TYPE` to actually disable fusion.

### GCS connectivity — `voxl-mavlink-server`

MAVLink UDP to GCS is configured in `/etc/modalai/voxl-mavlink-server.conf`.
The field `secondary_static_gcs_ip` sets a static push target (e.g., Mac's IP
on the LAN). Update it when the Mac's IP changes (DHCP):

```bash
# Replace old IP with new IP
sed -i 's/"secondary_static_gcs_ip":.*"OLD"/"secondary_static_gcs_ip":\t"NEW"/' \
    /etc/modalai/voxl-mavlink-server.conf

systemctl restart voxl-mavlink-server
```

QGC default listen port is `14550`.
