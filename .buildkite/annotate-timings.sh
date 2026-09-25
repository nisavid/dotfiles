#!/usr/bin/env bash
# Summarize the per-group timings that run-group.sh recorded as build meta-data.
set -euo pipefail

main() {
  local keys key value started finished status
  local earliest='' latest='' rows=''
  keys="$(buildkite-agent meta-data keys | grep '^timing:' | sort || true)"
  if [[ -z "$keys" ]]; then
    buildkite-agent annotate --style warning --context timings \
      'No group timings were recorded.'
    return 0
  fi
  while IFS= read -r key; do
    value="$(buildkite-agent meta-data get "$key")"
    read -r started finished status <<<"$value"
    rows+="| ${key#timing:} | $((finished - started))s | $status |"$'\n'
    if [[ -z "$earliest" || "$started" -lt "$earliest" ]]; then earliest=$started; fi
    if [[ -z "$latest" || "$finished" -gt "$latest" ]]; then latest=$finished; fi
  done <<<"$keys"
  buildkite-agent annotate --style info --context timings <<EOF
**Group timings** (first group start to last group finish: $((latest - earliest))s)

| OS:group | Duration | Exit |
| --- | --- | --- |
${rows}
EOF
}

main "$@"
