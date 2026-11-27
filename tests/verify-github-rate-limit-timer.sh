#!/bin/bash
# Run once after applying and starting the timer in the target Linux user session.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "$0")/.." && pwd)
cmp -s "$repo_root/home/private_dot_local/bin/executable_github-rate-limit" \
  "$HOME/.local/bin/github-rate-limit" || { echo 'Applied sampler differs from checkout' >&2; exit 1; }

systemctl --user is-active --quiet github-rate-limit.timer
systemctl --user list-timers --full --no-legend --no-pager github-rate-limit.timer |
  awk 'NF >= 2 && $(NF-1) == "github-rate-limit.timer" && $NF == "github-rate-limit.service" { listed = 1 }
       END { exit !listed }'

cursor=$(journalctl --user -b -n 1 -o json --output-fields=__CURSOR |
  jq -ers 'select(length == 1) | .[0].__CURSOR | strings | select(length > 0)')
now=$(date +%s)
first=$(( (now / 300 + 1) * 300 ))
# Allow one second of timer coalescing, two 2-second login checks, and the 30-second API read.
tolerance=35
sleep "$((first + 300 + tolerance + 1 - now))"

journalctl --user -b --after-cursor="$cursor" _SYSTEMD_USER_UNIT=github-rate-limit.service \
  -o json --output-fields=MESSAGE,_SYSTEMD_INVOCATION_ID |
  jq -es --argjson first "$first" --argjson tolerance "$tolerance" '
    map(.time = (.__REALTIME_TIMESTAMP | tonumber / 1000000) | select(.time >= $first))
    | length == 2
      and all(.[];
        (.MESSAGE | test("\\A[0-9]+( [0-9]+){7}\\z")) and
        (._SYSTEMD_INVOCATION_ID | test("\\A[0-9a-f]{32}\\z")))
      and (.[0]._SYSTEMD_INVOCATION_ID != .[1]._SYSTEMD_INVOCATION_ID)
      and (.[0].time <= $first + $tolerance)
      and (.[1].time >= $first + 300 and .[1].time <= $first + 300 + $tolerance)'
