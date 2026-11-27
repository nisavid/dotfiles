# GitHub rate-limit journal

On Linux, `github-rate-limit.timer` samples the active GitHub.com CLI login
at five-minute clock boundaries. To read the samples, run
`journalctl --user -u github-rate-limit.service -o cat`.

After applying the units, run `systemctl --user daemon-reload && systemctl --user start github-rate-limit.timer` to activate the timer. From the repository root, `bash tests/verify-github-rate-limit-timer.sh` checks the next two firings.

Each sample has eight space-separated integers. The first four describe
`core` (REST) and the last four describe `graphql`. In each group the
columns are the limit, remaining count, used count, and reset time in Unix
seconds. For example:

```text
5000 0 5000 1795800600 7000 6983 17 1795801200
```

The user service lets `gh` use its stored login in the user session. A failed
read writes `GitHub rate limit unavailable` and exits with an error. The next
scheduled run tries again.
