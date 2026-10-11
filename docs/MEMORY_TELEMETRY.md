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
`default.target.wants` symlink that enables it, on Linux only. It does not
start the unit; see [Operating it](#operating-it).

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
- the journal, through `journalctl` children: after a restart, one that reads
  everything after its saved position, then one that follows.

It writes only `~/.local/state/memory-telemetry`, created mode 0700 with files
mode 0600.

It never kills or signals a process other than its own `journalctl` children,
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
| fast | 10 s | T1, T2, T3 and T8, the shared counters, and T4 |
| slow | 60 s (every 6th fast sample) | Per-cgroup T3–T6, the oomd swap-holder ranking (T4), and T9 attribution |
| kill record | on each oomd or kernel OOM kill | T7 events with the preceding 15 minutes of samples |

oomd checks swap every 150 ms and acts with no duration, so #404 ruled out
5-minute polling. At 10 s, a 15-minute kill window holds 90 fast samples. The
per-process scan behind T9 is the costly part, so it runs every 60 s. When a
stall makes a tick late, the collector skips the ticks it missed rather than
catching up, and the next tick waits at least half an interval (5 s by default),
so two fast samples are never closer than that. It records how late each tick
ran in `collector.lag_ms`.

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
oldest hour first; the open hour is never deleted. At the measured volume (see
[Measured cost](#measured-cost)), the 30-day bound is the one that applies to
samples. `incidents/` keeps the newest 200 kill records, a record that is still
open included (see [Kill records](#kill-records)); at an estimated
0.7–0.8 MB each, that is up to about 150 MB more. One record's size and write
cost stay bounded whatever the journal delivers: it keeps at most 500 journal
events (see [Kill records](#kill-records)), and it is written only a few times
(see [Measured cost](#measured-cost)).

Each line in a segment and each `latest.json` has:

| Field | Meaning |
|---|---|
| `schema` | `memory-telemetry/v1` |
| `kind` | `fast` or `slow` |
| `t` | Unix time in seconds, wall clock, taken as the sample starts reading its sources |
| `boot` | The boot ID. Counters are comparable only within one boot. |
| `unavailable` | Present when a required source could not be read: source name to error class, such as `"proc:pressure/io": "FileNotFoundError"`. [When a source cannot be read](#when-a-source-cannot-be-read) lists the required sources and what the affected fields look like. Whether `journalctl` runs is reported in `collector.journal` instead. |
| `interval_s` | Fast samples only: seconds since the previous fast sample, at least half the configured interval. The sample that ran late after a stall has a long one, and its rates are averages over it. Absent from the first sample after a start or a boot change. |

Sizes ending in `_kib` are KiB as `/proc/meminfo` reports them; sizes ending in
`_bytes` are bytes as cgroup files and amdgpu report them.

### Fast samples

| Field | Signal | Source |
|---|---|---|
| `t1.mem_total_kib`, `t1.mem_available_kib` | T1 | `/proc/meminfo` |
| `t1.oomd_line_kib` | T1 | `(1 − SwapUsedLimit) × MemTotal`, below which oomd's memory condition holds |
| `t1.headroom_kib` | T1 | `MemAvailable − oomd_line_kib` |
| `t2.memory`, `t2.io` | T2 | `/proc/pressure/*`: `some` and `full`, each with `avg10`, `avg60`, `avg300` and `total_us` |
| `t2.cgroups.<name>` | T2 | `memory.pressure` of the user slice, `app.slice`, `builds.slice` and each watched cgroup |
| `t2.*.stall_fraction` | T2 | Share of the last interval stalled, from the `total_us` delta; absent from the first sample after a start or a boot change |
| `t3.counters` | T3 | `/proc/vmstat`: `pswpin`, `pswpout`, `zswpin`, `zswpout`, `zswpwb`, `workingset_refault_anon`, `pgmajfault`, `oom_kill`, and `allocstall` summed over zones |
| `t3.per_s` | T3 | Per-second rates over the last interval. Absent from the first sample after a start or a boot change; a counter that went down has no rate. |
| `t4.swap_*_kib`, `t4.swap_used_fraction` | T4 | Swap slot occupancy |
| `t4.zswap_pool_kib`, `t4.zswapped_kib` | T4 | The compressed pool and the memory it holds |
| `t4.disk_resident_upper_kib` | T4 | `swap used − Zswapped`, an upper bound on what is on disk |
| `t4.oomd_swap_gate_armed` | T4 | `SwapFree < (1 − SwapUsedLimit) × SwapTotal`: oomd now needs only T1 to cross its line |
| `t8.gtt_used_bytes`, `t8.devices` | T8 | amdgpu `mem_info_{gtt,vram}_{used,total}` |
| `t8.gpu_active_kib`, `t8.gpu_reclaim_kib` | T8 | `GPUActive`, `GPUReclaim` in `/proc/meminfo` |
| `oomd.swap_used_limit`, `oomd.source` | — | oomd's `SwapUsedLimit` and the file that set it, read like systemd reads `oomd.conf` and its drop-ins; `default`, or `default (configuration unreadable)` when a file could not be read |
| `collector` | — | The collector's own cost, cumulative since it started: `cpu_s`, `rss_anon_kib`, `rss_file_kib`, `hwm_kib`, `bytes_written` (samples, `latest.json`, kill records and the journal cursor), `lag_ms` (how late this tick ran), `journal`, `journal_ignored`, and while `journalctl` runs, its `journal_cpu_s`, `journal_rss_anon_kib` and `journal_rss_file_kib`. `journal` is always present: `starting` in a run's first sample, which is taken before `journalctl` starts; `catching up` while it reads the entries after its saved position; `following`; `exited: <status>`; or `unavailable: <error>`, which is also what a `--journalctl` command that cannot be run reports. `journal_ignored` counts the kill messages dropped since the start because they came from a sender other than the managers or repeated their `MESSAGE_ID` (see [Kill records](#kill-records)) |

### Slow samples

| Field | Signal | Contents |
|---|---|---|
| `swap_holders` | T4 | Leaf cgroups under oomd's roots (`system.slice` and the user slice by default) ranked by `memory.swap.current`, the top 10 with their swap share, `zswapped` and memory, how many exceed oomd's 5% candidacy floor, and `swap_mode_choice`: the cgroup oomd's swap mode would pick now, ignoring preferences |
| `cgroups.<name>` | T3–T6 | For the user slice, `app.slice`, `builds.slice` and each watched cgroup: `memory.current`, `memory.peak`, `memory.swap.current`, `memory.swap.peak`, a `memory.stat` subset, `memory.events.local` (`memory_events_local`) and the hierarchical `memory.events` (`memory_events`, which includes descendants, removed ones too), `memory.swap.events`, threads (`pids.current`, `pids.peak`, `pids.max`, `pids.events max`), `populated`, and for watched cgroups the process count |
| `t9.<name>` | T9 | For each watched cgroup: process count, the app's executable, totals, and the top 20 `classes` and `trees`, each with `processes`, `rss_anon_kib`, `swap_kib`, `rss_file_kib` and `rss_shmem_kib`, ranked by anonymous plus swapped memory. Smaller groups fold into one `(rest)` entry. |
| `removed.<name>` | T6 | The last counters seen for a watched cgroup whose directory is gone. A swap candidate that only fell below oomd's floor stops being sampled without appearing here. |
| `collector_cgroup` | — | The memory charged to the collector's cgroup (`cgroup`, `cgroup_memory_bytes`, `cgroup_memory_peak_bytes`), which includes `journalctl` and page cache from its writes; `null` when unreadable |

Watched cgroups are the user manager's `app.slice` children matching
`app-com.anthropic.Claude*`, `app-chatgpt@*` or `app-org.chromium.Chromium-*`,
plus any oomd swap candidate in this user's slice.

T9 groups processes two ways. A **class** is an executable basename plus a
role:

| Role | Process |
|---|---|
| `app` | Runs the app's own executable. The app is the root process with the largest subtree. |
| `agent` | A `claude` or `codex` executable other than the app's own. Claude Desktop's Electron binary is also named `claude`; the full path tells them apart in memory and is never recorded. Claude Code's native installer runs `…/claude/versions/<version>`, which counts and is recorded as `claude`. |
| `nested-agent` | An agent under another agent, such as a `codex exec` started from a Claude Code session |
| `agent-shell`, `agent-child` | An agent's other descendants: shells, and everything else, such as MCP servers |
| `app-child` | The app's other descendants |
| `detached` | Under another root, such as an orphan reparented to the user manager |

A **tree** is everything under one agent process, named like `claude[41872]`,
so each Claude Code session is one tree. The Codex app-server runs the tools
and MCP servers of all its threads as its own children, so a `codex` agent's
tree is split: the `codex` process alone is `codex[3301]`, and each direct
child's subtree is a tree of its own, such as `codex[3301]/node[3410]`. An agent
under any of these starts its own tree. Processes under no agent fall under
`(no agent)`. Executable and cgroup names come from other processes, so control
characters and invalid UTF-8 in them are recorded as backslash escapes.

### When a source cannot be read

These sources are required, and `unavailable` lists them when they cannot be
read:

- in fast samples: `/proc/meminfo`, `/proc/vmstat`, `/proc/pressure/memory`,
  `/proc/pressure/io`, the `memory.pressure` of the user slice and of
  `app.slice`, the `/sys/class/drm` directory, and any oomd configuration file
  or directory that exists but cannot be read or looked up (`config:` keys);
- in slow samples: `/proc/meminfo` and the directory of each oomd root.

Every other source is read without being listed: the `memory.pressure` of
`builds.slice` and of the watched cgroups, each device's `mem_info_*` files,
the cgroup files behind `cgroups.<name>` and `swap_holders`, the `/proc/<pid>`
files behind T9, and the boot ID. A field fed only by such a source is `null` or
missing, with no `unavailable` entry.

The shared counters then look like this:

| Source that cannot be read | Fields |
|---|---|
| `/proc/meminfo` | `t1`, `t4`, `t8.gpu_active_kib` and `t8.gpu_reclaim_kib` are `null` |
| `/proc/pressure/memory`, `/proc/pressure/io` | `t2.memory`, `t2.io` are `null` |
| A cgroup's `memory.pressure` | Its key is missing from `t2.cgroups` |
| `/proc/vmstat` | `t3.counters` is `{}`, and so is `t3.per_s` when present |
| `/sys/class/drm` | `t8.devices` is `[]` and `t8.gtt_used_bytes` is `null` |
| A device's `mem_info_<key>` | That device has no `<key>_bytes`; `t8.gtt_used_bytes` is `null` when no device has `gtt_used_bytes` |

### Kill records

Any of these journal entries opens a record (T7):

- systemd-oomd's own log saying it considered or marked cgroups for killing;
- systemd's `MESSAGE_ID=d989611b15e44c9dbf31e3c81256e4ed`, oomd killed processes in a unit;
- systemd's `MESSAGE_ID=fe6faa94e7774663a0da52717891d8ef`, the kernel OOM killer killed a process of a unit;
- one of the kernel's OOM report lines `<task> invoked oom-killer: gfp_mask=…`,
  `oom-kill:constraint=…`, or `Out of memory: Killed process …` (also
  `Memory cgroup out of memory: …`), each kept without its task name.

The kernel's `oom_reaper:` lines, oomd's candidate details, and any other kernel
line mentioning an OOM join an open record but never open one; such other lines
are kept only as `(kernel OOM line in an unrecognized format)`. Any process can
put an OOM word in its task name, and the kernel prints task names on lines of
their own (each row of an OOM report's task table, each segfault line), so a
record keeps at most 50 such lines.

A `MESSAGE_ID` is set by whoever writes the entry, and any local process can
write to the journal, so the two systemd messages count only when journald
itself, through the fields it sets and the sender cannot, attributes them to
the system manager (PID 1, `_UID=0`, `_SYSTEMD_UNIT=init.scope`) or to this
user's manager (`_UID` this user's, `_SYSTEMD_UNIT=user@<uid>.service`,
`_SYSTEMD_USER_UNIT=init.scope`). Those are the only senders of these messages in
this host's journal over the last 30 days. A message from any other sender opens
and joins nothing; it is counted in `collector.journal_ignored` and not
recorded. So is an entry that repeats `MESSAGE_ID` (`journalctl` prints the
values as a list) with one of the two among the values, whoever sent it: the
managers never repeat it. oomd's log and the kernel lines are told by
`_SYSTEMD_UNIT` and `_TRANSPORT`, which journald also sets.

A record keeps at most 500 events; this host's 30-day journal gives 1–22 per
record. An event new to the record that would go over a cap (500 events, or 50
kernel lines in an unrecognized format) is not kept and is counted in
`dropped_events`. A duplicate of a kept event changes nothing, but a dropped
event is not remembered, so reading it again, as the catch-up after a restart
can, counts it again.

An entry joins the newest record whose first entry is at or before it, if it is
no more than 60 s after that first entry, even if the record was closed on an
earlier tick or by an earlier collector process; it never joins a record whose
first entry is after it. Only the entry's time and the records' first entries
decide this, so an entry read again joins the record it joined the first time,
and a kill read in pieces or replayed after a restart makes one record. The
times are journald's receipt times, and `journalctl` delivers entries in that
order, each later than the one before it in this host's journal, so only a wall
clock that stepped back delivers an entry stamped before the first entry of a
record that already exists, or two entries with one time. An entry stamped
before is handled like one read again (a line that opens nothing is not kept,
and an opener gets a record of its own, finalized at once), so a kill whose
entries the step falls between can be left in two records; a line that opens
nothing, delivered just before an opener with the same time, is kept only if it
is read again. Each record holds:

| Field | Contents |
|---|---|
| `id` | UTC time of the first event and its kind, also the file name |
| `opened` | Unix time of the first event, in seconds; no event of the record is earlier |
| `events` | The journal events, in order, at most 500 |
| `dropped_events` | How many new events the record did not keep because they would have gone over a cap |
| `window.fast`, `window.slow` | Every sample from the 15 minutes before the first event: T1–T4 and T8, and the per-cgroup and T9 detail |
| `t9.latest` | The latest T9 attribution before the kill |
| `t9.growth` | The classes and trees whose anonymous plus swapped memory grew most. Only window samples from the latest sample's boot are compared, because sizes from another boot belong to other processes. Each is measured from the earliest of those samples that knows its size: one that lists it, or one whose list for its cgroup is complete (no `(rest)`), where it had nothing. Each item has `cgroup`, `section` (`classes` or `trees`), `exe` and `role` or `tree`, `anon_swap_kib` (its size now), `growth_kib`, `since` (the time of the sample it is measured from) and `new` (`true` when it had nothing then) |
| `t9.entered` | Classes and trees whose size no earlier window sample of that boot knows, because the sample lacked their cgroup (not yet watched, or its processes unreadable) or folded them into `(rest)`. Listed with the same identifying fields and `anon_swap_kib`, and no growth figure |
| `following.fast` | Fast samples from the 60 s after the first event |
| `finalized` | `true` once the 60 s have passed and the following samples are in. A collector that stops within the 60 s finalizes the record when it next starts. |

The kill record reads the window from the sample segments, so a kill found in
the journal after a restart still gets the samples recorded before it, and a
damaged compressed segment contributes the samples before the damage. The #366
`builds.slice` cap kills open records too.

The collector reads a stored record only to join, resume or finalize it, and
never reads one larger than 8 MiB, more than ten times a genuine record, so
that parsing one stays well inside the unit's `MemoryMax=128M` (a parsed record
takes about 4.7 times its file size at the peak). A larger record is left as it
is, never joined, resumed or finalized, until the 200-record cap deletes it; an
entry that would have joined it is handled as if it were absent, except that
its own first entry, read again, opens nothing in its place.

The record cap (`--max-incidents`, 200 by default) counts every record in
`incidents/`, one that is still open included. The collector enforces it as
each record is created and once at each start, deleting the oldest by first
event; a record opened while that many newer ones exist is deleted at once.
Late events that had joined a deleted record and were not written yet go with
it, and their entries no longer hold the saved journal position back.

## Reading the shared counters (#403)

1. Read `~/.local/state/memory-telemetry/latest.json`. Check `schema` and that
   `t` is no older than about three intervals (30 s); an older file means the
   collector is stopped or stalled.
2. Take T1 from `t1`, T2 from `t2` (the user slice is
   `t2.cgroups["user-<uid>.slice"]`, missing when its file could not be read;
   see [When a source cannot be read](#when-a-source-cannot-be-read)), T3 from
   `t3.per_s`, the swap gate from `t4.oomd_swap_gate_armed`, and T8 from `t8`.
   `t3.per_s` and `stall_fraction` are absent from the first sample after a
   start or a boot change; use the next sample.
3. For a window longer than one interval, read the `fast` lines of the sample
   segments and difference the counters between two samples with the same
   `boot`. PSI `total_us` gives exact stall time over any window.

Do not run a second collector.

## Threshold forms

The service implements none of these. Each is a form from #404 with its
numbers left open (#404 choice 7, after a baseline period); the record holds
the inputs each one needs, except the PSI of each job scope (see
[Not covered](#not-covered)).

| Signal | Form | Fields |
|---|---|---|
| T1 | Headroom below W for D s, with hysteresis; projected time to the line | `t1.headroom_kib` over time |
| T2 | `full` or `some` avg60 or avg300 above P for at least D | `t2.memory`, `t2.cgroups.<name>`, `stall_fraction` |
| T3 | Rate sustained over K windows and coinciding with rising T2 | `t3.per_s`, `cgroups.<name>.stat` |
| T4 | Informational "oomd swap gate armed" state | `t4.oomd_swap_gate_armed` |
| T5 | Baseline, growth slope, and fraction of `pids.max` | `cgroups.<name>.pids`, `cgroups.<name>.processes` |
| T6 | Any increment of `oom`, `oom_kill` or `oom_group_kill`; a sustained `high` or `max` rate together with rising job PSI | `cgroups.<name>.memory_events_local`; for events in children, removed ones included, `cgroups.<name>.memory_events` of the user slice, `app.slice` and `builds.slice`; for job PSI, `t2.cgroups["builds.slice"]`, all build jobs together |
| T7 | Any occurrence opens an incident | `incidents/` |
| T8 | GTT as a fraction of MemTotal, and its change per model load | `t8.gtt_used_bytes`, `t1.mem_total_kib` |
| T9 | Top contributors to an app scope's growth over a window | `t9`, `memory-telemetry report` |

Per #404, never alarm on any of these alone: SwapFree or
`memory.swap.events fail` while swap slots are full, `memory.current` (it
includes page cache and the charged zswap pool), `oomctl`'s per-cgroup swap
(stale by design), or a `memory.high` event rate.

## Measured cost

Measured on 2026-10-09 (UTC) over a 10-minute run at the default cadence
against the live host (kernel 7.2.9), while the watched cgroups held about
1,690 processes (611 in the Claude Desktop scope, 1,013 in the ChatGPT Chromium
scope) and oomd's roots held 163 leaf cgroups. Every figure comes from that
run's own records (the `collector` blocks, the record sizes, and the process
and cgroup counts in its last slow sample), except the reads, which come from
`/proc/<pid>/io` and `/usr/bin/time`. The highest values are those this run
observed, not bounds.

| Measure | Value |
|---|---|
| CPU per fast sample | about 2 ms (3 ms highest observed) |
| CPU per slow sample, including the T9 scan and the 163 leaf cgroups | about 75 ms (85 ms highest observed) |
| CPU at startup, including the first slow sample | about 130 ms |
| Average CPU of the collector | 0.13% of one core (0.78 s in 590 s) |
| Average CPU of its `journalctl` | about 0.015% of one core (0.09 s in 10 minutes without kill messages) |
| Memory of the collector | 15.6 MiB anonymous, 8.6 MiB file-backed, 24.3 MiB peak RSS |
| Memory of its `journalctl` | 0.8 MiB anonymous, 35.9 MiB of mapped journal files, which is reclaimable page cache and varies with how much of the journal is mapped (6.7 MiB in an earlier run) |
| Reads | Each `journalctl` start reads journal files to find where to start and the matching entries after it: 147 MB from disk in this run's first 20 s (its `read_bytes`; `/usr/bin/time` counted the same 147 MB of file-system input for the whole run), and 42 MB in an earlier run. How much comes from disk depends on how much of the 3.4 GB journal is in the page cache. In steady state it reads nothing more from disk, and the collector itself read 32 KiB: its `/proc` and `/sys` reads are not disk I/O. Each collector start, and each restart of `journalctl`, reads again, from the saved position when there is one. |
| Sample record | about 3.7 KB per fast sample and 21.7 KB per slow sample: about 63 MB a day uncompressed, about 8.5 MB a day once an hour is compressed (gzip, about 7×), so about 250 MB at 30 days |
| Other writes | `latest.json`, replaced every 10 s: about 32 MB a day |
| Tick lag | 1.4 ms highest observed |

The slow-sample cost grows with the number of processes in the watched
cgroups: the run's median slow sample took about 44 µs per process.

Kill records are not in these figures: no kill happened during the run, and
the kill-record path has been tested only with fixtures. Estimated from the
run's median sample sizes, a record holds about 90 fast and 15 slow samples
from its window, 6 following fast samples and its T9 summary, about 0.7–0.8 MB,
so the 200 records `incidents/` keeps take up to about 150 MB. A record is
written, and synced to disk, when it opens, at most once per tick while journal
events join it, and when it is finalized, however many events arrive. A kill
whose messages all arrive within one 10-s tick writes its record three times,
about 2 MB at that size; one whose events keep arriving for the whole 60 s
writes it at most about eight times, about 6 MB. At each start
the collector reads and parses every stored record to finalize any left open;
the startup figure above was measured with none stored. With 200 stored records
of 0.69 MB each, that parse took about 3.5 s of CPU per start, and 10–20 s of
wall time on a loaded host.

These are per-process figures from runs started by hand, outside the unit. The
memory charged to the unit's own cgroup, which also counts page cache from its
writes, is not yet measured; the service records it in each slow sample.

Each fast sample's `collector` records the collector's cumulative CPU time,
its anonymous and file-backed RSS, the same for its `journalctl` child, and the
bytes it has written, including kill records; each slow sample's
`collector_cgroup` records the memory charged to its cgroup. The cost stays
measured while it runs. The unit bounds the service
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
  `removed` keeps the last ones seen, and the parent slices' hierarchical
  `memory_events` still count the events. An `oom_kill` also shows in the
  T3 counters and as a kill record.
- **PSI of each job scope.** #404's T2 and T6 name each job scope's
  `memory.pressure`. Builds run as transient scopes inside `builds.slice`,
  whose PSI is recorded for all of them together. Each scope's own is not,
  because which slice will hold jobs, and how it relates to `builds.slice`, is
  #404 choice 1, still open.
- **PSI triggers.** Registering a kernel trigger is not needed while no
  threshold exists; the totals give exact stall time.
- **oomd's D-Bus `Killed` signal and units' `OOMKills`/`ManagedOOMKills`.** The
  journal carries the same events.
- **Warnings, admission refusal and cancellation.** These are later stages of
  #404 (S5) and separate decisions.

After a restart the collector first runs `journalctl` without `--follow` from
its saved position. That pass reads every matching entry after the position,
from every boot (with `--follow`, systemd 262 shows only the current boot), so
kills while the collector was stopped, before a reboot included, still get
records. It then follows from the newest entry the pass read. The same
catch-up runs whenever `journalctl` is restarted. If the saved position has
been rotated away, the pass starts from the oldest entry the journal still has
(as observed with systemd 262), and the collector replays everything since
without duplicating existing records. A position `journalctl` refuses as
malformed makes the collector start again from the journal's end. The
collector recognizes the refusal by exit status 1, no entry received, and
`journalctl`'s own message ("Failed to seek to cursor") on the catch-up pass's
standard error; it keeps nothing else from that output. A pass that fails any
other way (for example a signal, status 127, or another error) keeps the saved
position and runs again from it after the usual 30 s. Recognition rests on
`journalctl`'s English wording, verified on systemd 262 only. If another version
words the refusal differently, a malformed saved position is retried every 30 s,
showing as `exited: 1`, and nothing is read from the journal meanwhile, so no
kill gets a record. That lasts until `journal.cursor` is deleted and the
collector is then restarted
(`systemctl --user restart memory-telemetry.service`), after which it follows
from the journal's end. The journal's own retention depends on an unmanaged
journald setting.

The saved position is that of the last entry the collector finished handling,
not of the last one it read, and an entry is finished only once every
kill-record change it caused is written. Events that join a record wait in
memory for the next tick's write, so the position stays before them, and before
every entry read after them, until that write succeeds; a collector stopped by
`SIGTERM` writes them first and then saves the position. If handling an entry
fails, such as a kill record that cannot be written because the state directory
is full or not writable, the collector exits with the error, the position stays
before every entry whose change was not written, and the restart 30 s later
reads them again without duplicating what was written. While the failure
lasts, that repeats every 30 s, and each start also reads every stored kill
record.

## Operating it

chezmoi does not start or restart the unit. An existing `run_after_` script
(`home/run_after_activate-proton-pass-provider-ready.zsh.tmpl`) reloads the
user manager on every Linux apply, so after an apply the unit is loaded and
enabled. An enabled unit starts the next time the user manager starts: at the
next boot on this host, where lingering (`Linger=yes`) keeps the manager running
between logins, and at the next login on a host without it. To start it now, or
to restart it after an apply that changes it:

```zsh
systemctl --user daemon-reload && systemctl --user restart memory-telemetry.service
```

Inspect it:

```zsh
systemctl --user status memory-telemetry.service
memory-telemetry report              # latest counters, oomd's choice, T9 growth (new, entered), kill records
memory-telemetry report --window 3600
```

Try it without the service: `memory-telemetry sample` prints one fast and one
slow sample and writes nothing, and
`memory-telemetry run --state-dir "$(mktemp -d)" --duration 120` records for two
minutes into a new private scratch directory.

To turn it off, follow the comment at the top of
`home/dot_config/systemd/user/memory-telemetry.service`. The record stays until
deleted.
