#!/usr/bin/env python3
"""Apply a QGC-format .params file to PX4 via px4-param set.

Runs on the VOXL2 drone directly (px4-param is a VOXL binary, not standard PX4).

Usage:
    python3 apply_params.py <params_file> [--dry-run]
"""

import subprocess
import sys


def parse_qgc_params(path):
    """Parse a QGC .params file into (name, value) pairs.

    QGC format:
        # comment lines
        vehicle_id<TAB>component_id<TAB>name<TAB>value<TAB>type
    """
    params = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                continue
            name = parts[2]
            value = parts[3]
            params.append((name, value))
    return params


def apply(params, dry_run=False):
    ok = fail = 0
    for name, value in params:
        if dry_run:
            print(f'  [dry] px4-param set {name} {value}')
            ok += 1
            continue
        result = subprocess.run(
            ['px4-param', 'set', name, value],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f'  ok  {name} = {value}')
            ok += 1
        else:
            err = result.stderr.strip() or result.stdout.strip()
            print(f'  ERR {name}: {err}')
            fail += 1
    return ok, fail


def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    args = [a for a in args if not a.startswith('-')]

    if not args:
        print(f'Usage: {sys.argv[0]} <params_file> [--dry-run]')
        sys.exit(1)

    params = parse_qgc_params(args[0])
    print(f'{"[DRY RUN] " if dry_run else ""}Applying {len(params)} parameters from {args[0]}')

    ok, fail = apply(params, dry_run=dry_run)
    print(f'\n{ok} set, {fail} failed')
    if fail:
        sys.exit(1)


if __name__ == '__main__':
    main()
