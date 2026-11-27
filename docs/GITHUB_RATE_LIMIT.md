# GitHub rate-limit journal

On Linux, `github-rate-limit.timer` samples the host’s configured GitHub.com account
at five-minute clock boundaries. To read the samples, run
`journalctl --user _SYSTEMD_USER_UNIT=github-rate-limit.service -o short-iso`.

After applying the sampler, run `bash tests/verify-github-rate-limit-timer.sh --activate` from the merged checkout. It verifies the installed executable, both units, the wants link, and their chezmoi status before reloading the user manager and starting the timer. It then checks the next two firings.

Each sample has eight space-separated integers. The first four describe
`core` (REST) and the last four describe `graphql`. In each group the
columns are the limit, remaining count, used count, and reset time in Unix
seconds. For example:

```text
5000 0 5000 1795800600 7000 6983 17 1795801200
```

The user service uses the CLI’s stored credential. Immediately before and
after the free quota read, it compares the active login in the GitHub.com CLI
configuration with the expected login in the host’s deployed GitHub profile.
The sampler gives `gh` a fresh private copy of the host metadata for each
check. It accepts plain host and account mappings, logins, and Git protocols.
A token key or unrecognized configuration fails the sample. A switch to
another account and back between the checks goes undetected.

A mismatched, missing, or unreadable login or a failed quota read writes `GitHub rate limit unavailable` and exits with an error. The next
scheduled run tries again.
