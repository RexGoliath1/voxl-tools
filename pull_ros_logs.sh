#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
script="$script_dir/pull_ros_logs.py"

if command -v uv >/dev/null 2>&1; then
    exec uv run --script "$script" "$@"
fi

echo "warning: uv not found; falling back to python3 for $script" >&2
exec python3 "$script" "$@"
