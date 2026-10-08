# Memory telemetry

`memory-telemetry.service` is an observe-only systemd user service that samples
the host-memory signals T1–T9 defined in
[#404's resolution](https://github.com/nisavid/dotfiles/issues/404#issuecomment-5992180035),
section 4(b), and keeps its own durable record. It exists because systemd-oomd
has killed whole app scopes without warning
([incident record](https://github.com/nisavid/dotfiles/issues/404#issuecomment-6064101757)),
and nobody could see beforehand which process trees were growing. It
implements [#420](https://github.com/nisavid/dotfiles/issues/420).
[#403](https://github.com/nisavid/dotfiles/issues/403) reads its shared
counters instead of running a collector of its own.

chezmoi installs `~/.local/bin/memory-telemetry`, the unit, and a
`default.target.wants` symlink that enables it, on Linux only.

## What it does and does not do

It reads:

- `/proc/meminfo`, `/proc/vmstat` and `/proc/pressure/{memory,io}`;
- cgroup files under `/sys/fs/cgroup`: the user slice, the user manager's
  `app.slice` and `builds.slice`, the watched cgroups, and
  `memory.swap.current` of every leaf cgroup under oomd's monitored roots;
- `/proc/<pid>/status` and the `/proc/<pid>/exe` link of each process in a
  watched cgroup;
- `/sys/class/drm/card*/device/mem_info_*`;
- oomd's configuration, for `SwapUsedLimit`; and
- the journal, through a `journalctl --follow` child.

It writes only `~/.local/state/memory-telemetry`, created mode 0700 with files
mode 0600.

It never kills or signals a process other than its own `journalctl` child,
which it stops on exit. It changes no cgroup, unit, oomd, sysctl or swap
setting, unloads no model, and generates no load. It raises no alarms and sends
no notifications: the threshold numbers (#404 choice 7) and the warning
modality (#404 choice 8) are still open.

It never records a command line, argument, environment variable or task name
(`comm`), because those can carry credentials. A process is named by the
basename of its executable and a coarse role from the process tree. Journal
entries keep only `MESSAGE_ID`, `MESSAGE`, `UNIT`, `USER_UNIT`,
`_SYSTEMD_UNIT`, `_BOOT_ID` and the timestamp, and kernel OOM lines lose their
task names.

## Cadence

| Sample | Every | Contents |
|---|---|---|
| fast | 10 s | T1, T2, T3, T4 and T8: the shared counters |
| slow | 60 s (every 6th fast sample) | Per-cgroup T3–T6, the oomd swap-holder ranking (T4), and T9 attribution |
| kill record | on each oomd or kernel OOM kill | T7 events with the preceding 15 minutes of samples |

oomd checks swap every 150 ms and acts with no duration, so #404 ruled out
5-minute polling. At 10 s, a 15-minute kill window holds 90 fast samples. The
per-process scan behind T9 is the costly part, so it runs every 60 s. The
collector skips ticks it misses during a stall rather than catching up, and
records how late each tick ran in `collector.lag_ms`.

`run` takes `--interval`, `--slow-every`, `--window` (seconds of samples kept
before a kill), `--grace` (seconds during which later kill messages join the
same record, and of samples kept after it), `--retention-days`,
`--max-sample-bytes`, `--max-incidents`, `--watch` and `--oomd-root`. The unit
uses the defaults.

## The record

```text
~/.local/state/memory-telemetry/
├── latest.json                        newest fast sample, replaced atomically
├── samples/20261008T16.jsonl          the current UTC hour, one JSON object per line
├── samples/20261008T15.jsonl.gz       closed hours, compressed
├── incidents/20261008T155523.333881Z-oomd-kill.json   one kill record per incident
└── journal.cursor                     where to resume reading the journal
```

Retention keeps samples for 30 days and at most 512 MiB in total, deleting the
oldest hour first; the open hour is never deleted. Incidents keep the newest
200 records. At the measured volume (see [Measured cost](#measured-cost)), the
30-day bound is the one that applies.

Each line in a segment and each `latest.json` has:

| Field | Meaning |
|---|---|
| `schema` | `memory-telemetry/v1` |
| `kind` | `fast` or `slow` |
| `t` | Unix time in seconds, wall clock |
| `boot` | The boot ID. Counters are comparable only within one boot. |
| `unavailable` | Present when a source could not be read: source name to error class, such as `"proc:pressure/io": "FileNotFoundError"`. The matching fields are `null`. |

Sizes ending in `_kib` are KiB as `/proc/meminfo` reports them; sizes ending in
`_bytes` are bytes as cgroup files and amdgpu report them.

### Fast samples

| Field | Signal | Source |
|---|---|---|
| `t1.mem_total_kib`, `t1.mem_available_kib` | T1 | `/proc/meminfo` |
| `t1.oomd_line_kib` | T1 | `(1 − SwapUsedLimit) × MemTotal`, below which oomd's memory condition holds |
| `t1.headroom_kib` | T1 | `MemAvailable − oomd_line_kib` |
| `t2.memory`, `t2.io` | T2 | `/proc/pressure/*`: `some` and `full`, each with `avg10`, `avg60`, `avg300` and `total_us` |
| `t2.cgroups.<name>` | T2 | `memory.pressure` of the user slice, `app.slice` and each watched cgroup |
| `t2.*.stall_fraction` | T2 | Share of the last interval stalled, from the `total_us` delta |
| `t3.counters` | T3 | `/proc/vmstat`: `pswpin`, `pswpout`, `zswpin`, `zswpout`, `zswpwb`, `workingset_refault_anon`, `pgmajfault`, `oom_kill`, and `allocstall` summed over zones |
| `t3.per_s` | T3 | Per-second rates over the last interval; omitted for a counter that went down |
| `t4.swap_*_kib`, `t4.swap_used_fraction` | T4 | Swap slot occupancy |
| `t4.zswap_pool_kib`, `t4.zswapped_kib` | T4 | The compressed pool and the memory it holds |
| `t4.disk_resident_upper_kib` | T4 | `swap used − Zswapped`, an upper bound on what is on disk |
| `t4.oomd_swap_gate_armed` | T4 | `SwapFree < (1 − SwapUsedLimit) × SwapTotal`: oomd now needs only T1 to cross its line |
| `t8.gtt_used_bytes`, `t8.devices` | T8 | amdgpu `mem_info_{gtt,vram}_{used,total}` |
| `t8.gpu_active_kib`, `t8.gpu_reclaim_kib` | T8 | `GPUActive`, `GPUReclaim` in `/proc/meminfo` |
| `oomd.swap_used_limit`, `oomd.source` | — | oomd's `SwapUsedLimit` and the file that set it, read like systemd reads `oomd.conf` and its drop-ins |
| `collector` | — | The collector's own cost: see [Measured cost](#measured-cost) |

### Slow samples

| Field | Signal | Contents |
|---|---|---|
| `swap_holders` | T4 | Leaf cgroups under oomd's roots (`system.slice` and the user slice by default) ranked by `memory.swap.current`, the top 10 with their swap share, `zswapped` and memory, how many exceed oomd's 5% candidacy floor, and `swap_mode_choice`: the cgroup oomd's swap mode would pick now, ignoring preferences |
| `cgroups.<name>` | T3–T6 | For the user slice, `app.slice`, `builds.slice` and each watched cgroup: `memory.current`, `memory.peak`, `memory.swap.current`, `memory.swap.peak`, a `memory.stat` subset, `memory.events.local`, `memory.swap.events`, threads (`pids.current`, `pids.peak`, `pids.max`, `pids.events max`), `populated`, and for watched cgroups the process count |
| `t9.<name>` | T9 | For each watched cgroup: process count, the app's executable, totals, and the top 20 `classes` and `trees`, each with `processes`, `rss_anon_kib`, `swap_kib`, `rss_file_kib` and `rss_shmem_kib`, ranked by anonymous plus swapped memory. Smaller groups fold into one `(rest)` entry. |
| `removed.<name>` | T6 | The last counters seen for a watched cgroup that has since disappeared |

Watched cgroups are the user manager's `app.slice` children matching
`app-com.anthropic.Claude*`, `app-chatgpt@*` or `app-org.chromium.Chromium-*`,
plus any oomd swap candidate in this user's slice.

T9 groups processes two ways. A **class** is an executable basename plus a
role:

| Role | Process |
|---|---|
| `app` | Runs the app's own executable. The app is the root process with the largest subtree. |
| `agent` | A `claude` or `codex` executable other than the app's own. Claude Desktop's Electron binary is also named `claude`; the full path tells them apart in memory and is never recorded. |
| `nested-agent` | An agent under another agent, such as a `codex exec` started from a Claude Code session |
| `agent-shell`, `agent-child` | An agent's other descendants: shells, and everything else, such as MCP servers |
| `app-child` | The app's other descendants |
| `detached` | Under another root, such as an orphan reparented to the user manager |

A **tree** is everything under one agent process, named like `claude[41872]`;
processes under no agent fall under `(no agent)`.

### Kill records

Any of these journal entries opens a record (T7):

- systemd-oomd's own log saying it considered or marked cgroups for killing;
- systemd's `MESSAGE_ID=d989611b15e44c9dbf31e3c81256e4ed`, oomd killed processes in a unit;
- systemd's `MESSAGE_ID=fe6faa94e7774663a0da52717891d8ef`, the kernel OOM killer killed a process of a unit;
- a kernel OOM report line.

Entries within 60 s of the first join the same record. Each record holds:

| Field | Contents |
|---|---|
| `id`, `opened` | UTC time of the first event and its kind |
| `events` | The journal events, in order |
| `window.fast`, `window.slow` | Every sample from the 15 minutes before the first event: T1–T4 and T8, and the per-cgroup and T9 detail |
| `t9.latest`, `t9.growth` | The latest T9 attribution before the kill, and the classes and trees whose anonymous plus swapped memory grew most across the window |
| `following.fast` | Fast samples from the 60 s after the first event |
| `finalized` | `true` once the 60 s have passed |

The kill record reads the window from the sample segments, so a kill found in
the journal after a restart still gets the samples recorded before it. A
replayed event does not duplicate a record. The #366 `builds.slice` cap kills
open records too.

## Reading the shared counters (#403)

1. Read `~/.local/state/memory-telemetry/latest.json`. Check `schema` and that
   `t` is no older than about three intervals (30 s); an older file means the
   collector is stopped or stalled.
2. Take T1 from `t1`, T2 from `t2`, T3 from `t3.per_s`, the swap gate from
   `t4.oomd_swap_gate_armed`, and T8 from `t8`.
3. For a window longer than one interval, read the `fast` lines of the sample
   segments and difference the counters between two samples with the same
   `boot`. PSI `total_us` gives exact stall time over any window.

Do not run a second collector.

## Threshold forms

The service implements none of these. Each is a form from #404 with its
numbers left open (#404 choice 7, after a baseline period); the record holds
the inputs each one needs.

| Signal | Form | Fields |
|---|---|---|
| T1 | Headroom below W for D s, with hysteresis; projected time to the line | `t1.headroom_kib` over time |
| T2 | `full` or `some` avg60 or avg300 above P for at least D | `t2.memory`, `t2.cgroups.<name>`, `stall_fraction` |
| T3 | Rate sustained over K windows and coinciding with rising T2 | `t3.per_s`, `cgroups.<name>.stat` |
| T4 | Informational "oomd swap gate armed" state | `t4.oomd_swap_gate_armed` |
| T5 | Baseline, growth slope, and fraction of `pids.max` | `cgroups.<name>.pids`, `cgroups.<name>.processes` |
| T6 | Any increment of `oom`, `oom_kill` or `oom_group_kill`; a sustained `high` or `max` rate together with rising PSI | `cgroups.<name>.memory_events_local` |
| T7 | Any occurrence opens an incident | `incidents/` |
| T8 | GTT as a fraction of MemTotal, and its change per model load | `t8.gtt_used_bytes`, `t1.mem_total_kib` |
| T9 | Top contributors to an app scope's growth over a window | `t9`, `memory-telemetry report` |

Per #404, never alarm on any of these alone: SwapFree or
`memory.swap.events fail` while swap slots are full, `memory.current` (it
includes page cache and the charged zswap pool), `oomctl`'s per-cgroup swap
(stale by design), or a `memory.high` event rate.

## Measured cost

Measured on 2026-10-08 over a 10-minute run at the default cadence against the
live host (kernel 7.2.9, about 430 processes in the Claude Desktop scope and
630 in the ChatGPT Chromium scope, 162 leaf cgroups under oomd's roots):

| Measure | Value |
|---|---|
| CPU per fast sample | about 2 ms |
| CPU per slow sample, including the T9 scan of about 1,100 processes and the 162 leaf cgroups | about 48 ms (53 ms at most) |
| CPU at startup | about 100 ms |
| Average CPU of the collector | 0.09% of one core (0.53 s in 590 s) |
| Average CPU of its `journalctl` | about 0.01% of one core (0.07 s in 10 minutes without kill messages) |
| Memory of the collector | 14.2 MiB anonymous, 8.6 MiB file-backed, 22.9 MiB peak RSS |
| Memory of its `journalctl` | 0.7 MiB anonymous, 33.7 MiB of mapped journal files, which is reclaimable page cache |
| Sample record | about 3.7 KB per fast sample and 19.7 KB per slow sample: about 60 MB a day uncompressed, about 9 MB a day once an hour is compressed (gzip, about 6.8×), so about 270 MB at 30 days |
| Other writes | `latest.json`, replaced every 10 s: about 32 MB a day |
| Tick lag | at most 3 ms |

These are per-process figures from runs started by hand, outside the unit. The
memory charged to the unit's own cgroup, which also counts page cache from its
writes, is not yet measured; the service records it in each slow sample.

Each fast and slow sample records the collector's cumulative CPU time, its
anonymous and file-backed RSS, the same for its `journalctl` child, and the
bytes it has written, and each slow sample records the memory charged to its
cgroup, so the cost stays measured while it runs. The unit bounds the service
at `MemoryMax=128M`, with `MemorySwapMax=0` so it keeps sampling when swap is
full, and runs it at `Nice=10` with the lowest best-effort I/O priority.

## Not covered

- **T8 per client.** DRM fdinfo scans cost 0.15–2 s, and fdinfo of the
  inference services, which run as other users, is unreadable to this user.
  Only the global counters are recorded.
- **T9 shared and proportional memory.** `smaps_rollup` (`Pss_Anon`,
  `SwapPss`) takes 1.6 s across the app scopes and briefly takes each
  process's mmap lock, so it is not sampled. RSS double-counts shared pages,
  `VmSwap` includes zswap, and processes that live less than 60 s are missed.
- **T9 outside this user.** System services are ranked by swap but their
  processes are not attributed.
- **Event-driven T6.** cgroup event files are read every 60 s rather than
  watched, so `.local` counters of a cgroup removed between samples are lost;
  `removed` keeps the last ones seen.
- **PSI triggers.** Registering a kernel trigger is not needed while no
  threshold exists; the totals give exact stall time.
- **oomd's D-Bus `Killed` signal and units' `OOMKills`/`ManagedOOMKills`.** The
  journal carries the same events.
- **Warnings, admission refusal and cancellation.** These are later stages of
  #404 (S5) and separate decisions.

If the saved journal position has been rotated away, the collector restarts
from the journal's end, so kills in that gap get no record. The journal's own
retention depends on an unmanaged journald setting.

## Operating it

After `chezmoi apply` installs or changes it:

```zsh
systemctl --user daemon-reload && systemctl --user restart memory-telemetry.service
```

Inspect it:

```zsh
systemctl --user status memory-telemetry.service
memory-telemetry report              # the latest counters, oomd's choice, T9 growth, kill records
memory-telemetry report --window 3600
```

Try it without the service: `memory-telemetry sample` prints one fast and one
slow sample and writes nothing, and
`memory-telemetry run --state-dir /tmp/memory-telemetry-trial --duration 120`
records for two minutes into a scratch directory.

To turn it off, follow the comment at the top of
`home/dot_config/systemd/user/memory-telemetry.service`. The record stays until
deleted.
