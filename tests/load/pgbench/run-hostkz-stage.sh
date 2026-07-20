#!/usr/bin/env bash
set -euo pipefail

clients=${1:?clients required}
duration=${2:-30}
rate=${3:-0}
label=${4:-c${clients}-r${rate}}
result_root=${RESULT_ROOT:-/home/kamilya/loadtest-results}
result_dir="$result_root/$label"
pgpass=${PGPASSFILE:-/home/kamilya/.pgpass-loadtest}
read_script=${READ_SCRIPT:-/home/kamilya/migration/learner-read.sql}
write_script=${WRITE_SCRIPT:-/home/kamilya/migration/learner-progress.sql}

mkdir -p "$result_dir"
threads=$clients
if (( threads > 8 )); then
    threads=8
fi

vmstat 1 $((duration + 3)) > "$result_dir/vmstat.txt" &
vmstat_pid=$!
iostat -xz 1 $((duration + 3)) > "$result_dir/iostat.txt" &
iostat_pid=$!
pidstat -h -u -r -d -C 'postgres|pgbouncer' 1 $((duration + 3)) \
    > "$result_dir/pidstat.txt" &
pidstat_pid=$!

command=(
    pgbench -n
    -h 127.0.0.1 -p 6432 -U lms_app
    -c "$clients" -j "$threads" -T "$duration" -P 10
    -l --sampling-rate=0.1 --log-prefix="$result_dir/pgbench-"
    -f "$read_script@4" -f "$write_script@1"
)
if (( rate > 0 )); then
    command+=( -R "$rate" )
fi
command+=( kamilya_lms_test )

set +e
PGPASSFILE="$pgpass" "${command[@]}" > "$result_dir/summary.txt" 2>&1
status=$?
set -e

wait "$vmstat_pid" "$iostat_pid" "$pidstat_pid" || true

python3 - "$result_dir" <<'PY'
from __future__ import annotations

import glob
import math
import pathlib
import sys

result_dir = pathlib.Path(sys.argv[1])
latencies = []
for path in glob.glob(str(result_dir / "pgbench-*")):
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) >= 3:
                latencies.append(int(parts[2]) / 1000)

latencies.sort()
for percentile in (50, 95, 99):
    if latencies:
        index = min(len(latencies) - 1, math.ceil(len(latencies) * percentile / 100) - 1)
        print(f"sample_p{percentile}_ms={latencies[index]:.3f}")
print(f"sample_count={len(latencies)}")
PY

cat "$result_dir/summary.txt"
exit "$status"
