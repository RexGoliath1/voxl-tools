#!/usr/bin/env python3
"""Set voxl-mavlink-server's static GCS IP over adb or SSH.

This script runs on macOS or Linux. It talks to a connected Starling/VOXL over
adb shell by default, updates /etc/modalai/voxl-mavlink-server.conf, backs up
the original file on the drone, and restarts voxl-mavlink-server. SSH mode is
available when a drone IP is provided.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass


DEFAULT_REMOTE_USER = "root"
DEFAULT_REMOTE_PASSWORD = "oelinux123"
DEFAULT_CONFIG_PATH = "/etc/modalai/voxl-mavlink-server.conf"
DEFAULT_FIELD = "secondary_static_gcs_ip"
DEFAULT_SERVICE = "voxl-mavlink-server"


REMOTE_EDITOR = r'''
import datetime
import os
import re
import shutil
import subprocess
import sys

path, field, ip, service, dry_run, restart = sys.argv[1:]
dry_run = dry_run == "1"
restart = restart == "1"

try:
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
except OSError as exc:
    print(f"ERROR: failed to read {path}: {exc}", file=sys.stderr)
    sys.exit(2)

pattern = re.compile(r'("' + re.escape(field) + r'"\s*:\s*")([^"]*)(")')
match = pattern.search(text)
if not match:
    known = sorted(set(re.findall(r'"([^"]*static_gcs_ip)"\s*:', text)))
    known_msg = ", ".join(known) if known else "none found"
    print(f"ERROR: field {field!r} was not found in {path}", file=sys.stderr)
    print(f"Known static GCS IP fields: {known_msg}", file=sys.stderr)
    sys.exit(3)

old_ip = match.group(2)
new_text, count = pattern.subn(r"\g<1>" + ip + r"\3", text, count=1)
print(f"{field}: {old_ip or '<empty>'} -> {ip}")

if dry_run:
    print("dry run: remote config was not changed and service was not restarted")
    sys.exit(0)

timestamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
backup_path = f"{path}.bak.{timestamp}"
try:
    shutil.copy2(path, backup_path)
    tmp_path = f"{path}.tmp-{os.getpid()}"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp_path, path)
except OSError as exc:
    print(f"ERROR: failed to update {path}: {exc}", file=sys.stderr)
    sys.exit(4)

print(f"backup: {backup_path}")
print(f"updated: {path}")

if restart:
    result = subprocess.run(
        ["systemctl", "restart", service],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        print(f"ERROR: systemctl restart {service} failed", file=sys.stderr)
        sys.exit(result.returncode)

    status = subprocess.run(
        ["systemctl", "is-active", service],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    print(f"{service}: {status.stdout.strip() or 'unknown'}")
else:
    print(f"restart skipped: run `adb shell systemctl restart {service}` when ready")
'''


@dataclass(frozen=True)
class Args:
    transport: str
    ip: str | None
    interface: str | None
    drone_ip: str | None
    user: str
    password: str
    ssh_port: int
    serial: str | None
    field: str
    config: str
    service: str
    adb: str
    dry_run: bool
    no_restart: bool


def run(
    cmd: list[str],
    *,
    input_text: str | None = None,
    check: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"{cmd[0]!r} was not found") from exc
    if check and result.returncode != 0:
        joined = " ".join(cmd)
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        detail = stderr or stdout or f"exit code {result.returncode}"
        raise RuntimeError(f"{joined} failed: {detail}")
    return result


def validate_ipv4(value: str) -> str:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if ip.version != 4:
        raise argparse.ArgumentTypeError("expected an IPv4 address")
    return value


def detect_ip_for_interface(interface: str) -> str:
    system = platform.system()
    if system == "Darwin":
        result = run(["ipconfig", "getifaddr", interface], check=False)
        ip = result.stdout.strip()
        if result.returncode == 0 and ip:
            return validate_ipv4(ip)
        raise RuntimeError(f"could not find an IPv4 address for interface {interface!r}")

    result = run(["ip", "-4", "addr", "show", "dev", interface], check=False)
    if result.returncode == 0:
        match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)/", result.stdout)
        if match:
            return validate_ipv4(match.group(1))

    result = run(["ifconfig", interface], check=False)
    if result.returncode == 0:
        match = re.search(r"\binet (?:addr:)?(\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return validate_ipv4(match.group(1))

    raise RuntimeError(f"could not find an IPv4 address for interface {interface!r}")


def detect_route_ip(target: str) -> str:
    # UDP connect does not send traffic; it asks the OS which local address it
    # would use to reach the target. This works on macOS and Linux.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target, 80))
        return validate_ipv4(sock.getsockname()[0])
    except OSError as exc:
        raise RuntimeError("could not auto-detect host IPv4 address; rerun with --ip or --interface") from exc
    finally:
        sock.close()


def adb_base(adb: str, serial: str | None) -> list[str]:
    cmd = [adb]
    if serial:
        cmd.extend(["-s", serial])
    return cmd


def parse_adb_devices(output: str) -> list[str]:
    devices: list[str] = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def ensure_adb_device(args: Args) -> None:
    run([args.adb, "start-server"])
    if args.serial:
        state = run(adb_base(args.adb, args.serial) + ["get-state"]).stdout.strip()
        if state != "device":
            raise RuntimeError(f"adb device {args.serial!r} is not ready; state is {state!r}")
        return

    result = run([args.adb, "devices"])
    devices = parse_adb_devices(result.stdout)
    if not devices:
        raise RuntimeError("no adb device found; connect the Starling and confirm `adb devices`")
    if len(devices) > 1:
        listed = ", ".join(devices)
        raise RuntimeError(f"multiple adb devices found ({listed}); rerun with --serial")


def run_adb_remote_update(args: Args, ip: str) -> None:
    cmd = adb_base(args.adb, args.serial) + [
        "shell",
        "python3",
        "-",
        args.config,
        args.field,
        ip,
        args.service,
        "1" if args.dry_run else "0",
        "0" if args.no_restart else "1",
    ]
    result = run(cmd, input_text=REMOTE_EDITOR, check=False)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"remote update failed with exit code {result.returncode}")


def ssh_base(args: Args) -> tuple[list[str], dict[str, str] | None]:
    env = None
    cmd: list[str] = []
    if args.password:
        sshpass = shutil.which("sshpass")
        if not sshpass:
            raise RuntimeError(
                "SSH password mode requires sshpass; install it or use SSH keys with --password ''"
            )
        env = os.environ.copy()
        env["SSHPASS"] = args.password
        cmd.extend([sshpass, "-e"])

    cmd.extend(
        [
            "ssh",
            "-p",
            str(args.ssh_port),
            "-o",
            "StrictHostKeyChecking=accept-new",
            f"{args.user}@{args.drone_ip}",
        ]
    )
    return cmd, env


def run_ssh_remote_update(args: Args, ip: str) -> None:
    cmd, env = ssh_base(args)
    cmd.extend(
        [
            "python3",
            "-",
            args.config,
            args.field,
            ip,
            args.service,
            "1" if args.dry_run else "0",
            "0" if args.no_restart else "1",
        ]
    )
    result = run(cmd, input_text=REMOTE_EDITOR, check=False, env=env)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"remote update failed with exit code {result.returncode}")


def run_remote_update(args: Args, ip: str) -> None:
    if args.transport == "adb":
        ensure_adb_device(args)
        run_adb_remote_update(args, ip)
        return

    if args.transport == "ssh":
        if not args.drone_ip:
            raise RuntimeError("SSH mode requires --drone-ip")
        run_ssh_remote_update(args, ip)
        return

    raise RuntimeError(f"unsupported transport {args.transport!r}")


def parse_args(argv: list[str]) -> Args:
    parser = argparse.ArgumentParser(
        description="Set a Starling/VOXL MAVLink static GCS IP over adb shell or SSH.",
    )
    parser.add_argument("--ip", type=validate_ipv4, help="host computer IP to write; default is auto-detected")
    parser.add_argument("-i", "--interface", help="local interface to read IP from, e.g. en0 or wlan0")
    parser.add_argument(
        "--transport",
        choices=("adb", "ssh"),
        help="remote transport; default: adb, or ssh when --drone-ip is provided",
    )
    parser.add_argument("--drone-ip", "--host", dest="drone_ip", help="drone IP for SSH mode")
    parser.add_argument("--user", default=DEFAULT_REMOTE_USER, help=f"SSH username; default: {DEFAULT_REMOTE_USER}")
    parser.add_argument(
        "--password",
        default=DEFAULT_REMOTE_PASSWORD,
        help="SSH password for sshpass; use --password '' for SSH keys",
    )
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port; default: 22")
    parser.add_argument("-s", "--serial", help="adb serial when more than one device is connected")
    parser.add_argument(
        "--field",
        default=DEFAULT_FIELD,
        help=f"config field to update; default: {DEFAULT_FIELD}",
    )
    parser.add_argument(
        "--primary",
        action="store_const",
        dest="field",
        const="primary_static_gcs_ip",
        help="shortcut for --field primary_static_gcs_ip",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help=f"remote config path; default: {DEFAULT_CONFIG_PATH}")
    parser.add_argument("--service", default=DEFAULT_SERVICE, help=f"systemd service to restart; default: {DEFAULT_SERVICE}")
    parser.add_argument("--adb", default="adb", help="adb executable path; default: adb")
    parser.add_argument("--dry-run", action="store_true", help="show what would change without editing or restarting")
    parser.add_argument("--no-restart", action="store_true", help="update config but do not restart the service")
    ns = parser.parse_args(argv)
    transport = ns.transport or ("ssh" if ns.drone_ip else "adb")
    return Args(
        transport=transport,
        ip=ns.ip,
        interface=ns.interface,
        drone_ip=ns.drone_ip,
        user=ns.user,
        password=ns.password,
        ssh_port=ns.ssh_port,
        serial=ns.serial,
        field=ns.field,
        config=ns.config,
        service=ns.service,
        adb=ns.adb,
        dry_run=ns.dry_run,
        no_restart=ns.no_restart,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.transport == "ssh" and not args.drone_ip:
            raise RuntimeError("SSH mode requires --drone-ip")
        default_target = args.drone_ip if args.transport == "ssh" and args.drone_ip else "8.8.8.8"
        ip = args.ip or (detect_ip_for_interface(args.interface) if args.interface else detect_route_ip(default_target))
        print(f"host IP: {ip}")
        run_remote_update(args, ip)
    except (RuntimeError, argparse.ArgumentTypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
