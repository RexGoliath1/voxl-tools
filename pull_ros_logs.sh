#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./pull_ros_logs.sh [options] <ssh-target>

Pull Brecourt ROS 2 logs from a VOXL/Starling over SSH/SCP.

Default behavior is auto:
  1. Copy host-mounted saved logs if a deployed run.sh wrote ROS_LOG_DIR to
     brecourt/log/ros on the drone host.
  2. Otherwise copy logs from a brecourt-ros2 Docker container. This works for
     a running container and for a stopped container if it still exists.

Arguments:
  ssh-target                    SSH target, e.g. root@192.168.1.57

Options:
  -o, --output-dir DIR          Local destination root. Default: ./ros_logs
  -s, --source auto|host|docker Source to use. Default: auto
  -c, --container ID|NAME       Docker container to copy from. Default: newest
                                container matching brecourt-ros2.
  --container-log-dir DIR       Container log dir to try first. Can be repeated.
                                Defaults include ROS_LOG_DIR, /root/brecourt/log/ros,
                                and /root/.ros/log.
  --host-log-dir DIR            Host-side saved ROS log dir to try. Can be
                                repeated. Defaults include common Brecourt
                                deploy paths and discovered */brecourt/log/ros.
  --remote-repo-dir DIR         Add DIR/brecourt/log/ros as a host log candidate.
  --no-discover                 Do not search common remote roots for
                                */brecourt/log/ros.
  -h, --help                    Show this help.

Local layout:
  <output-dir>/<ssh-target-label>/<ROS datetime log directories>

Examples:
  ./pull_ros_logs.sh root@192.168.1.57
  ./pull_ros_logs.sh --source docker root@192.168.1.57
  ./pull_ros_logs.sh --source host --remote-repo-dir /data/brecourt_tflite_tracker root@192.168.1.57
  ./pull_ros_logs.sh -o ~/ros_logs root@192.168.1.57
EOF
}

output_dir="./ros_logs"
source_mode="auto"
container=""
discover_host_logs=1
host_log_dirs=()
container_log_dirs=()

join_by_pipe() {
    local IFS='|'
    printf '%s' "$*"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output-dir)
            output_dir="${2:-}"
            shift 2
            ;;
        -s|--source)
            source_mode="${2:-}"
            shift 2
            ;;
        -c|--container)
            container="${2:-}"
            shift 2
            ;;
        --container-log-dir)
            container_log_dirs+=("${2:-}")
            shift 2
            ;;
        --host-log-dir)
            host_log_dirs+=("${2:-}")
            shift 2
            ;;
        --remote-repo-dir)
            host_log_dirs+=("${2%/}/brecourt/log/ros")
            shift 2
            ;;
        --no-discover)
            discover_host_logs=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        -*)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
        *)
            break
            ;;
    esac
done

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

case "$source_mode" in
    auto|host|docker) ;;
    *)
        echo "Invalid --source: $source_mode" >&2
        exit 2
        ;;
esac

ssh_target="$1"
if [[ -z "$output_dir" ]]; then
    echo "--output-dir cannot be empty" >&2
    exit 2
fi

if [[ ${#host_log_dirs[@]} -eq 0 ]]; then
    host_log_dirs=(
        "/root/brecourt_tflite_tracker/brecourt/log/ros"
        "/home/root/brecourt_tflite_tracker/brecourt/log/ros"
        "/data/brecourt_tflite_tracker/brecourt/log/ros"
        "/data/brecourt/brecourt/log/ros"
        "/home/gonk/git/Brecourt/brecourt_tflite_tracker/brecourt/log/ros"
    )
fi

if [[ ${#container_log_dirs[@]} -eq 0 ]]; then
    container_log_dirs=(
        "/root/brecourt/log/ros"
        "/root/.ros/log"
    )
fi

target_label=$(printf '%s' "$ssh_target" | tr '@/:' '___' | tr -cd '[:alnum:]_.-')
dest_dir="${output_dir%/}/${target_label}"
mkdir -p "$dest_dir"

host_dirs_arg=$(join_by_pipe "${host_log_dirs[@]}")
container_dirs_arg=$(join_by_pipe "${container_log_dirs[@]}")

remote_output=$(mktemp "${TMPDIR:-/tmp}/voxl_ros_logs_remote.XXXXXX")
cleanup_remote_output() {
    rm -f "$remote_output"
}
trap cleanup_remote_output EXIT

if ! ssh "$ssh_target" bash -s -- \
    "$source_mode" "$container" "$host_dirs_arg" "$container_dirs_arg" "$discover_host_logs" \
    >"$remote_output" <<'REMOTE'
set -euo pipefail

source_mode="${1:-auto}"
container="${2:-}"
host_dirs_arg="${3:-}"
container_dirs_arg="${4:-}"
discover_host_logs="${5:-1}"

IFS='|' read -r -a host_dirs <<< "$host_dirs_arg"
IFS='|' read -r -a container_dirs <<< "$container_dirs_arg"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
tmp_dir="/tmp/voxl_ros_logs_${stamp}_$$"
copy_dir="$tmp_dir/log"
archive="$tmp_dir/ros_logs.tar.gz"

cleanup() {
    rm -rf "$tmp_dir"
}
trap cleanup EXIT
mkdir -p "$copy_dir"

has_entries() {
    find "$1" -mindepth 1 -print -quit 2>/dev/null | grep -q .
}

copy_host_logs() {
    local dir
    for dir in "${host_dirs[@]}"; do
        [[ -n "$dir" ]] || continue
        if [[ -d "$dir" ]] && has_entries "$dir"; then
            echo "source=host:$dir" >&2
            tar -C "$dir" -cf - . | tar -C "$copy_dir" -xf -
            return 0
        fi
    done

    if [[ "$discover_host_logs" == "1" ]]; then
        while IFS= read -r dir; do
            if [[ -d "$dir" ]] && has_entries "$dir"; then
                echo "source=host:$dir" >&2
                tar -C "$dir" -cf - . | tar -C "$copy_dir" -xf -
                return 0
            fi
        done < <(
            find /data /root /home/root /home/gonk -type d -path '*/brecourt/log/ros' -print 2>/dev/null \
                | sort -r
        )
    fi

    return 1
}

select_container() {
    if [[ -n "$container" ]]; then
        printf '%s\n' "$container"
        return 0
    fi

    local selected
    selected="$(
        docker ps --format '{{.ID}} {{.Image}} {{.Names}}' 2>/dev/null \
            | awk '$0 ~ /brecourt-ros2/ {print $1; exit}'
    )"
    if [[ -n "$selected" ]]; then
        printf '%s\n' "$selected"
        return 0
    fi

    docker ps -a --format '{{.ID}} {{.Image}} {{.Names}}' 2>/dev/null \
        | awk '$0 ~ /brecourt-ros2/ {print $1; exit}'
}

container_env_ros_log_dir() {
    local selected="$1"
    docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$selected" 2>/dev/null \
        | awk -F= '$1 == "ROS_LOG_DIR" && $2 != "" {print $2; exit}'
}

try_docker_cp_dir() {
    local selected="$1"
    local dir="$2"
    local attempt="$tmp_dir/docker_attempt"
    rm -rf "$attempt"
    mkdir -p "$attempt"

    if docker cp "${selected}:${dir}/." "$attempt" >/dev/null 2>&1 && has_entries "$attempt"; then
        echo "source=docker:${selected}:${dir}" >&2
        tar -C "$attempt" -cf - . | tar -C "$copy_dir" -xf -
        return 0
    fi

    return 1
}

copy_container_logs() {
    local selected
    selected="$(select_container || true)"
    if [[ -z "$selected" ]]; then
        echo "ERROR: no brecourt-ros2 Docker container found" >&2
        return 1
    fi

    if ! docker inspect "$selected" >/dev/null 2>&1; then
        echo "ERROR: Docker container not found: $selected" >&2
        return 1
    fi

    local env_ros_log_dir
    env_ros_log_dir="$(container_env_ros_log_dir "$selected" || true)"
    if [[ -n "$env_ros_log_dir" ]]; then
        try_docker_cp_dir "$selected" "$env_ros_log_dir" && return 0
    fi

    local dir
    for dir in "${container_dirs[@]}"; do
        [[ -n "$dir" ]] || continue
        try_docker_cp_dir "$selected" "$dir" && return 0
    done

    echo "ERROR: no non-empty ROS log directory found in Docker container $selected" >&2
    return 1
}

case "$source_mode" in
    host)
        copy_host_logs || {
            echo "ERROR: no non-empty host-mounted ROS log directory found" >&2
            exit 3
        }
        ;;
    docker)
        copy_container_logs || exit 4
        ;;
    auto)
        copy_host_logs || copy_container_logs || {
            echo "ERROR: no ROS logs found in host-mounted paths or Docker" >&2
            exit 5
        }
        ;;
esac

if ! has_entries "$copy_dir"; then
    echo "ERROR: staged log directory is empty" >&2
    exit 6
fi

tar -C "$copy_dir" -czf "$archive" .
trap - EXIT
printf '%s\n' "$archive"
REMOTE
then
    echo "ERROR: failed to stage ROS logs on remote host" >&2
    exit 8
fi

remote_result=$(cat "$remote_output")
rm -f "$remote_output"
trap - EXIT

remote_archive=$(printf '%s\n' "$remote_result" | tail -n 1)
if [[ -z "$remote_archive" ]]; then
    echo "ERROR: remote did not report an archive path" >&2
    exit 7
fi

local_archive=$(mktemp "${TMPDIR:-/tmp}/voxl_ros_logs.XXXXXX.tar.gz")
cleanup_local() {
    rm -f "$local_archive"
}
trap cleanup_local EXIT

scp "${ssh_target}:${remote_archive}" "$local_archive"
ssh "$ssh_target" "rm -rf \"\$(dirname '$remote_archive')\""

tar -xzf "$local_archive" -C "$dest_dir"

echo "Copied ROS logs to: $dest_dir"
