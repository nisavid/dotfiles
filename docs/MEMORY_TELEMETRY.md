# Memory telemetry

`memory-telemetry.service` is an observe-only systemd user service that samples
the host-memory signals T1–T9 defined in
[#404's resolution](https://github.com/nisavid/dotfiles/issues/404#issuecomment-5992180035),
section 4(b), and keeps its own durable record. It exists because systemd-oomd
has killed whole app scopes without warning
([incident record](https://github.com/nisavid/dotfiles/issues/404#issuecomment-6064101757)),
and nobody could see beforehand which process trees were growing. It
implements [#420](https://github.com/nisavid/dotfiles/issues/420), with the
observe-only measurement extension for
[#405](https://github.com/nisavid/dotfiles/issues/405).
[#403](https://github.com/nisavid/dotfiles/issues/403) reads its shared
counters instead of running a collector of its own.

chezmoi installs `~/.local/bin/memory-telemetry`, the unit, and a
`default.target.wants` symlink that enables it, on Linux only. It does not
start the unit; see [Operating it](#operating-it).

## What it does and does not do

It reads:

- `/proc/meminfo`, `/proc/vmstat`, `/proc/pressure/{memory,io,cpu}`,
  `/proc/stat`, `/proc/swaps`, `/proc/diskstats`, `/proc/zoneinfo`,
  `/proc/buddyinfo`, and the dentry/inode state counters;
- cgroup files under `/sys/fs/cgroup`: the user slice, the user manager's
  `app.slice` and `builds.slice`, the watched cgroups, and
  memory and swap use of every leaf cgroup under its configured oomd roots,
  with detailed accounting for the largest holders and inference services;
- `/proc/<pid>/status` and the `/proc/<pid>/exe` link of each process in a
  watched cgroup;
- `/sys/class/drm/card*/device/mem_info_*`;
- VM, zswap, MGLRU, and THP settings, kernel and boot identity, oomd's
  configuration for `SwapUsedLimit`, and read-only `oomctl` snapshots; and
- the journal, through `journalctl` children: after a restart, one that reads
  everything after its saved position, then one that follows.

It writes only `~/.local/state/memory-telemetry`, created mode 0700 with files
mode 0600.

It stops its own `journalctl` children on exit and bounds each read-only
`oomctl` child with a three-second timeout. It never kills or signals another
process. It changes no cgroup, unit, oomd, sysctl or swap setting, unloads
no model, and starts no workload. It raises no alarms and sends
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
| fast | 10 s | T1, T2, T3, T4, and T8; capacity, CPU time, swap areas, and storage counters |
| slow | 60 s (every 6th fast sample) | Per-cgroup T3–T6, holder rankings, T9 attribution, and reserve/metadata-cache counts |
| metadata | start, first tick of each new UTC day, and orderly end | Recorder, kernel, policy settings, and effective oomd snapshot |
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
uses the defaults. `run` and `sample` also accept `--oomctl` to select the
read-only snapshot command.

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
oldest hour first; the open hour is never deleted. The original recorder's
measured volume fit within the size bound for 30 days
(see [Measured cost](#measured-cost)); the extension's projected volume can
reach the size bound sooner. `incidents/` keeps the newest 200 kill records, a record
that is still open included (see [Kill records](#kill-records)); the original
recorder's 0.7–0.8 MB estimate per record gave about 150 MB more. Larger
extension samples also enlarge incident windows, so that estimate is a
baseline only. One record's size and write cost stay bounded whatever the
journal delivers: it keeps at most 500 journal
events (see [Kill records](#kill-records)), and it is written only a few times
(see [Measured cost](#measured-cost)).

Segments contain fast, slow, and metadata records; `latest.json` remains the
newest fast sample. All three record kinds have:

| Field | Meaning |
|---|---|
| `schema` | `memory-telemetry/v1` |
| `schema_revision` | `2` for the additive #405 extension. Existing T1–T9 fields retain their meanings; original records may omit this field. Consumers must select the record kinds and fields they understand. |
| `kind` | `fast`, `slow`, or `metadata` |
| `t` | Unix time in seconds, wall clock, taken as the sample starts reading its sources |
| `boot` | The boot ID, or `null` when unreadable. Counters are comparable only within one known boot. |
| `unavailable` | Present when a required source could not be read: source name to error class, such as `"proc:pressure/io": "FileNotFoundError"`. [When a source cannot be read](#when-a-source-cannot-be-read) lists the required sources and what the affected fields look like. Whether `journalctl` runs is reported in `collector.journal` instead. |
| `interval_s` | Fast samples only: seconds since the previous fast sample, at least half the configured interval. The sample that ran late after a stall has a long one, and its rates are averages over it. Absent from the first sample after a start or a boot change, and whenever the boot ID is unknown. |

Sizes ending in `_kib` are KiB as `/proc/meminfo` reports them; sizes ending in
`_bytes` are bytes as cgroup files and amdgpu report them.

### Fast samples

| Field | Signal | Source |
|---|---|---|
| `t1.mem_total_kib`, `t1.mem_available_kib` | T1 | `/proc/meminfo` |
| `t1.oomd_line_kib` | T1 | `(1 − SwapUsedLimit) × MemTotal`, below which oomd's memory condition holds |
| `t1.headroom_kib` | T1 | `MemAvailable − oomd_line_kib` |
| `t2.cpu` | — | System CPU PSI `some` only, with the same averages and total as memory/I/O PSI; system CPU `full` is omitted |
| `t2.memory`, `t2.io` | T2 | `/proc/pressure/*`: `some` and `full`, each with `avg10`, `avg60`, `avg300` and `total_us` |
| `t2.cgroups.<name>` | T2 | `memory.pressure` of the user slice, `app.slice`, `builds.slice` and each watched cgroup |
| `t2.*.stall_fraction` | T2 | Share of the last interval stalled, from the `total_us` delta; absent from the first sample after a start or a boot change, or when the boot ID is unknown |
| `t3.counters` | T3 | `/proc/vmstat`: swap, reclaim, compaction, and THP counters listed below, individual `allocstall_*` counters, and `allocstall` summed over zones |
| `t3.per_s` | T3 | Per-second rates over the last interval. Absent from the first sample after a start or a boot change, or when the boot ID is unknown; a counter that went down has no rate. |
| `t4.swap_*_kib`, `t4.swap_used_fraction` | T4 | Swap slot occupancy |
| `t4.zswap_pool_kib`, `t4.zswapped_kib` | T4 | The compressed pool and the memory it holds |
| `t4.disk_resident_upper_kib` | T4 | `swap used − Zswapped`, an upper bound on what is on disk |
| `t4.oomd_swap_gate_armed` | T4 | `SwapFree < (1 − SwapUsedLimit) × SwapTotal`: oomd now needs only T1 to cross its line |
| `t8.gtt_used_bytes`, `t8.devices` | T8 | amdgpu `mem_info_{gtt,vram}_{used,total}` |
| `t8.gpu_active_kib`, `t8.gpu_reclaim_kib` | T8 | `GPUActive`, `GPUReclaim` in `/proc/meminfo` |
| `oomd.swap_used_limit`, `oomd.source` | — | oomd's `SwapUsedLimit` and the file that set it, read like systemd reads `oomd.conf` and its drop-ins; `default`, or `default (configuration unreadable)` when a file could not be read |
| `capacity_kib` | — | `/proc/meminfo` fields `MemFree`, `Cached`, `SwapCached`, `SReclaimable`, `SUnreclaim`, `Unevictable`, `Mlocked`, `Committed_AS`, `CommitLimit`, and `AnonHugePages`; original kernel field names are retained |
| `swap_areas` | — | `/proc/swaps`: each area's `path`, `type`, `size_kib`, `used_kib`, and `priority` |
| `cpu.time_ticks`, `cpu.per_s` | — | Aggregate `/proc/stat` CPU times: `user`, `nice`, `system`, `idle`, `iowait`, `irq`, `softirq`, `steal`, `guest`, and `guest_nice`; rates are ticks per second, not percentages. Metadata supplies `clock_ticks_per_s`. |
| `diskstats.<name>` | — | Whole NVMe devices (`nvme…n…`), device-mapper (`dm-*`), and RAID (`md*`) layers from `/proc/diskstats`, each kept separately; no partition rows. Each has `device` (major:minor), `diskseq`, `counters`, and the current `in_flight` gauge. |
| `collector` | — | The collector's own cost, cumulative since it started: `cpu_s`, `oomctl_cpu_s` (cumulative child CPU for metadata snapshots), `rss_anon_kib`, `rss_file_kib`, `hwm_kib`, `bytes_written` (samples, `latest.json`, kill records and the journal cursor), `lag_ms` (how late this tick ran), `journal`, `journal_ignored`, and while `journalctl` runs, its `journal_cpu_s`, `journal_rss_anon_kib` and `journal_rss_file_kib`. `journal` is always present: `starting` in a run's first sample, which is taken before `journalctl` starts; `catching up` while it reads the entries after its saved position; `following`; `exited: <status>`; or `unavailable: <error>`, which is also what a `--journalctl` command that cannot be run reports. `journal_ignored` counts the kill messages dropped since the start because they came from a sender other than the managers or repeated their `MESSAGE_ID` (see [Kill records](#kill-records)) |

The complete `t3.counters` allowlist is:

- Swap and faults: `pswpin`, `pswpout`, `zswpin`, `zswpout`, `zswpwb`,
  `pgmajfault`, `oom_kill`, `swap_ra`, `swap_ra_hit`, `swpin_zero`, and
  `swpout_zero`.
- Reclaim: `workingset_refault_anon`, `workingset_refault_file`,
  `workingset_activate_anon`, `workingset_activate_file`,
  `workingset_restore_anon`, `workingset_restore_file`, `pgscan_anon`,
  `pgscan_file`, `pgsteal_anon`, `pgsteal_file`, `pgscan_kswapd`,
  `pgscan_direct`, `pgsteal_kswapd`, `pgsteal_direct`,
  `kswapd_low_wmark_hit_quickly`, `kswapd_high_wmark_hit_quickly`, and every
  available `allocstall_*`, plus their `allocstall` sum.
- Compaction: `compact_stall`, `compact_fail`, `compact_success`,
  `compact_migrate_scanned`, and `compact_free_scanned`.
- THP: `thp_fault_alloc`, `thp_fault_fallback`, `thp_fault_fallback_charge`,
  `thp_collapse_alloc`, `thp_collapse_alloc_failed`, `thp_split_page`,
  `thp_split_page_failed`, `thp_deferred_split_page`, `thp_split_pmd`,
  `thp_swpout`, and `thp_swpout_fallback`.

Each disk's `counters` contains `reads`, `writes`, `read_sectors`,
`write_sectors`, `read_ms`, `write_ms`, `io_ms`, and `weighted_io_ms`.
`per_s` uses the same keys and actual elapsed seconds. It is emitted only when
both observations have the same major:minor and the same non-null `diskseq`,
within one known boot. Device names are discovered before taking the counter
snapshot; sequence reads bracket that snapshot. A newly appeared device or
one whose sequence changes during acquisition is omitted for that sample.
A missing disk sequence number leaves raw counters
usable but suppresses rates. Device replacement, a missing preceding device,
and a counter decrease suppress the affected rates; `in_flight` is a gauge
and never gets a rate. Host VM and CPU rates and PSI stall fractions likewise
require consecutive observations within one known boot; a missing or decreased
counter gets no derived value. A long interval after a stall still produces
an average over that interval.

### Slow samples

| Field | Signal | Contents |
|---|---|---|
| `swap_holders` | T4 | Leaf cgroups under oomd's roots (`system.slice` and the user slice by default) ranked by `memory.swap.current`, the top 10 with their swap share, `zswapped` and memory, how many exceed oomd's 5% candidacy floor, and `swap_mode_choice`: the cgroup oomd's swap mode would pick now, ignoring preferences |
| `cgroups.<name>` | T3–T6 | For each selected cgroup: `memory.current`, `memory.peak`, `memory.swap.current`, `memory.swap.peak`, `memory.zswap.current`, complete numeric `memory.stat` (`stat`), `memory.events.local` (`memory_events_local`) and the hierarchical `memory.events` (`memory_events`, which includes descendants, removed ones too), `memory.swap.events`, threads (`pids.current`, `pids.peak`, `pids.max`, `pids.events max`), `populated`, and for watched cgroups the process count |
| `t9.<name>` | T9 | For each watched cgroup: process count, the app's executable, totals, and the top 20 `classes` and `trees`, each with `processes`, `rss_anon_kib`, `swap_kib`, `rss_file_kib` and `rss_shmem_kib`, ranked by anonymous plus swapped memory. Smaller groups fold into one `(rest)` entry. |
| `removed.<name>` | T6 | The last counters seen for a sampled cgroup whose directory is gone. A group no longer selected but still present does not appear here. |
| `reserves` | — | `/proc/zoneinfo` as `zones.<node>:<zone>` with `free`, `min`, `low`, `high`, `boost`, and `managed` in pages; `/proc/buddyinfo` as `buddy.<node>:<zone>` arrays from allocation order 0 upward; `dentry_state` and `inode_state` arrays in their kernel field order |
| `collector_cgroup` | — | The memory charged to the collector's cgroup (`cgroup`, `cgroup_memory_bytes`, `cgroup_memory_peak_bytes`), which includes `journalctl` and page cache from its writes; `null` when unreadable |

Watched cgroups are the user manager's `app.slice` children matching
`app-com.anthropic.Claude*`, `app-chatgpt@*` or `app-org.chromium.Chromium-*`,
plus any oomd swap candidate in this user's slice.

Detailed cgroup selection is the union of:

- the user slice, `app.slice`, `builds.slice`, and existing watched cgroups;
- the five largest memory holders and five largest swap holders from the
  existing walk under the configured oomd roots (`system.slice` and this
  user's slice by default);
- visited cgroups matching `lemon*.service`, `ollama*.service`,
  `open-webui*.service`, or `inference*.service`;
- `jobs.slice` at the cgroup root and under this user's manager, when present.

The walk treats a directory without child cgroups, or one with
`memory.oom.group=1`, as a leaf and stops descending there. Holder rankings
therefore use these oomd-style units, rather than arbitrary parent totals.
Inference matches can include a parent visited before its children. A group
hidden beneath a stop point is outside this walk's coverage. `top_by_swap`
keeps its existing top ten; `swap_holders.top_by_memory` lists the top five.
Additional groups use their cgroup-relative paths as keys. The existing T9
watch selection and process scan are unchanged: extra holders, inference
services, and jobs slices receive file-based accounting only.

Each detailed `cgroups.<name>` block also has:

| Field | Contents |
|---|---|
| `path`, `identity` | Cgroup-relative path and `[st_dev, st_ino]` from its directory. Identity is checked again after reading; a changed identity drops that block. |
| `limits` | This group's `memory.high`, `memory.max`, `memory.swap.high`, `memory.swap.max`, and `memory.zswap.max`, as bytes, `"max"`, or `null` |
| `effective_limits`, `limits_unavailable` | The minimum finite configured bound along the group and its ancestors, excluding the cgroup root. These bounds are shared with siblings, not remaining headroom. An unreadable value anywhere in the chain makes that effective bound `null`; the corresponding cgroup-relative file paths appear in `limits_unavailable`. All-readable unlimited values yield `"max"`. |
| `pressure` | `memory`, `io`, and `cpu` PSI averages and totals, read from this cgroup's pressure files |
| `cpu_stat` | Available `usage_usec`, `user_usec`, `system_usec`, `nr_throttled`, and `throttled_usec` counters |
| `io_stat` | Per-major:minor `rbytes`, `wbytes`, `rios`, and `wios` counters |

These cgroup statistics are raw observations; the recorder derives no slow
cgroup rates. Before calculating deltas, require the same known boot, path,
and directory identity, a continuous observation interval, and nondecreasing
counters. The identity pair is evidence of continuity, not a permanent ID;
inode reuse and manual resets still need consideration. Full `memory.stat`
contains gauges as well as counters, including kernel fields the recorder does
not interpret. Apply the meaning and units of each field before comparing it.
Fast `t2.cgroups` stall fractions match cgroups by name without checking
directory identity; use continuity evidence before relying on them across a
cgroup lifecycle transition.

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
- in slow samples: `/proc/meminfo` and the directory of each oomd root;
- in metadata: the kernel release and each requested VM, zswap, MGLRU, and THP
  setting, plus unreadable oomd configuration. Optional kernel settings absent
  on that kernel are therefore explicit gaps too.

Every other source is read without being listed: the `memory.pressure` of
`builds.slice` and of the watched cgroups, each device's `mem_info_*` files,
the cgroup files behind `cgroups.<name>` and `swap_holders`, the `/proc/<pid>`
files behind T9, the new fast and reserve sources, and the boot ID. A field fed only by such a source is `null` or
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

For added observations, unreadable `/proc/swaps` or `/proc/diskstats` gives
`null`; readable sources with no accepted rows give `[]` or `{}`. Missing
capacity or VM counter keys are omitted, and missing `/proc/stat` gives an
empty `cpu.time_ticks`. System CPU PSI is `null` when unavailable. Reserve
sources use `null` for unreadable zone/buddy files and unreadable or malformed
dentry/inode arrays. A readable but unparsed zone/buddy file gives `{}`.
Cgroup numeric files and pressure resources use `null`, keyed statistics use
`{}` or omit unavailable keys, and a cgroup with unreadable `memory.current`
or identity is omitted entirely. None of these values means zero activity.

### Metadata snapshots

`kind=metadata` records share the hourly segments and retention with samples;
they do not replace `latest.json` or enter the fast/slow incident windows.
`reason` is `start` on the first tick, `daily` on the first tick whose UTC date
differs from the preceding tick, or `end` on orderly collector close. Missed
days are not backfilled, and an abrupt kill can leave no end snapshot.
`sample` prints one additional metadata object with `reason=sample`.

| Field | Contents |
|---|---|
| `recorder_sha256` | SHA-256 of the recorder source read at collector start, or `null` if unreadable |
| `kernel`, `boot`, `page_size_bytes`, `clock_ticks_per_s` | Kernel release, boot ID, and units for page and CPU accounting |
| `vm` | `swappiness`, `page-cluster`, `vfs_cache_pressure`, `min_free_kbytes`, `watermark_scale_factor`, `watermark_boost_factor`, `overcommit_memory`, `overcommit_ratio`, and `overcommit_kbytes` |
| `zswap` | `enabled`, `compressor`, `zpool`, `max_pool_percent`, `accept_threshold_percent`, and `shrinker_enabled` |
| `mglru` | `enabled` and `min_ttl_ms` |
| `thp` | `enabled`, `defrag`, `shmem_enabled`, `use_zero_page`, `khugepaged/defrag`, `khugepaged/pages_to_scan`, `khugepaged/scan_sleep_millisecs`, and `khugepaged/alloc_sleep_millisecs`; `sizes` adds `enabled` and `shmem_enabled` for each discovered `hugepages-<size>kB` directory |
| `oomd` | File-derived `swap_used_limit` and `source`, plus `effective` from `oomctl --no-pager dump` |

Settings retain their text, including bracketed selected values, or `null`
with an `unavailable` entry. Effective oomd output retains only global dry-run,
swap, and default memory-pressure limits/duration in `global`, monitored
swap paths in `swap_monitored`, and paths with their pressure limits/duration
in `pressure_monitored`. Unrecognized output is
not stored. `oomd.effective.unavailable` reports command failure, timeout, or an
unrecognized format, independently of the source-file `unavailable` map.
Each attempt records `cpu_s` and `duration_ms`; fast samples' cumulative
`collector.oomctl_cpu_s` accounts for completed snapshots.

Each snapshot uses a short-lived, unprivileged read-only subprocess. It adds
no daemon, second collector, or process scan. Daily settings snapshots cannot
locate a mid-day rollout precisely; keep the manual workload and configuration
timeline described in the [seven-day procedure](#seven-day-ordinary-operation-measurement).

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
never reads one larger than 8 MiB. This bounds parsing cost; the original
recorder's measurement found about 4.7 times the file size at the peak.
This bound alone does not qualify the whole
service under `MemoryMax=128M`; see [Measured cost](#measured-cost). A larger record is left as it
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
   start or a boot change, and while the boot ID is unknown. Wait for
   consecutive samples with a known boot ID.
3. For a window longer than one interval, read the `fast` lines of the sample
   segments and difference counters with a known, unchanged `boot`. Apply
   the source-specific continuity and reset checks above. PSI `total_us`
   gives stall time over the accepted window.

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

The following is the **original recorder baseline**, before the #405
extension. Measured on 2026-10-09 (UTC) over a 10-minute run at the default cadence
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

These are per-process figures from runs started by hand, outside the unit.
That baseline did not measure memory charged to the unit's cgroup, which also
counts page cache from its writes; the service records it in each slow sample.

Each fast sample's `collector` records the collector's cumulative CPU time,
its anonymous and file-backed RSS, the same for its `journalctl` child, and the
bytes it has written, including kill records; each slow sample's
`collector_cgroup` records the memory charged to its cgroup. The cost stays
measured while it runs. The unit bounds the service
at `MemoryMax=128M`, uses `MemorySwapMax=0` to keep the collector out of swap,
and runs it at `Nice=10` with the lowest best-effort I/O priority.

### Extension sampling cost

On 2026-10-17, a bounded comparison called the public fast sampler six times
and the slow sampler twice against the ordinary live host, then persisted
their real records and `latest.json` into a scratch directory with the
recorder's existing writers. The extension also took one real metadata
snapshot. No collector, journal reader, service, extra process scan, or
synthetic workload was started. Memory PSI some/full avg10 was zero in the
final extension run; MemAvailable was about 43.1% of RAM and swap use 59.2%.

The baseline was source commit `c9d740e9102cda826cfa0bbd69a1e2cda780fa7c`.
The extension source SHA-256 was
`7c1a3cb26386954128bc8a3cc603be9241816bec1b3dc7ff66fac5c853830fa4`;
its bytes stayed unchanged during measurement. CPU and wall times below
include sampling, compact serialization, and the real scratch writes.

| Observed mean | Baseline | Extension |
|---|---:|---:|
| Fast CPU / wall | 0.505 / 0.508 ms | 1.678 / 1.694 ms |
| Slow CPU / wall | 23.089 / 23.142 ms | 38.032 / 38.331 ms |
| Benchmark process peak RSS | 28.4 MiB | 30.6 MiB |

The metadata record was 2,788 bytes: 1.54 ms of parent CPU, 3.49 ms of child
CPU, and 5.39 ms elapsed through persistence. The short-lived `oomctl` child
peaked at 5.3 MiB RSS. Child CPU includes the measurement wrapper; its RSS
figure covers `oomctl` alone. These process peaks were measured separately,
and the benchmark includes its helper and retained previous samples.

At the default cadence, the observed rate-bearing record sizes project to
173.9 MB/day of raw samples and 96.6 MB/day of `latest.json` rewrites: about
270.5 MB/day of logical payload before compression, versus 63.8 MB/day for
the bounded baseline comparison. The same timing projection gives about
69.3 seconds/day of sampling and persistence CPU (0.080% of one core), versus
37.6 seconds/day for the baseline. Three metadata captures add about
0.010 seconds/day of child CPU. These are estimates from back-to-back calls,
not observed daily service totals or a controlled workload comparison.

The actual small samples file was 173,513 bytes and gzipped to 28,098 bytes.
Applying that measured ratio projects about 28.2 MB/day of compressed samples,
or about 197 MB for seven days. A small-file ratio is no retention guarantee;
at this projection the 512 MiB size cap would bind before 30 days. Retention
remains bounded by the existing age and size rules.

This comparison omits `Collector.tick`'s extra fields, journal/cursor and
incident writes, filesystem amplification, and compression writes. It
measures no scheduling or tick lag and qualifies no full journal catch-up,
incident recovery, or service-cgroup memory peak. The deployed recorder's
existing `collector` and `collector_cgroup` fields supply those observations
during the seven-day window; `collector.oomctl_cpu_s` adds snapshot-child CPU.

`MemoryMax=128M` and `MemorySwapMax=0` are unchanged. The existing journal
catch-up headroom limitation tracked in
[#426](https://github.com/nisavid/dotfiles/issues/426) remains unresolved by
this extension. This task does not qualify a new service deployment under
that limit; per-process scratch measurements cannot establish service-cgroup
headroom during journal catch-up.

## Not covered

- **T8 per client.** DRM fdinfo scans cost 0.15–2 s, and fdinfo of the
  inference services, which run as other users, is unreadable to this user.
  Only the global counters are recorded.
- **T9 shared and proportional memory.** `smaps_rollup` (`Pss_Anon`,
  `SwapPss`) takes 1.6 s across the app scopes and briefly takes each
  process's mmap lock, so it is not sampled. RSS double-counts shared pages,
  `VmSwap` includes zswap, and processes that live less than 60 s are missed.
- **T9 outside this user.** Large memory/swap holders and matching inference
  services receive cgroup statistics, but their processes are not attributed.
- **Event-driven T6.** cgroup event files are read every 60 s rather than
  watched, so `.local` counters of a cgroup removed between samples are lost;
  `removed` keeps the last ones seen, and the parent slices' hierarchical
  `memory_events` still count the events. An `oom_kill` also shows in the
  T3 counters and as a kill record.
- **PSI of each job scope.** #404's T2 and T6 name each job scope's
  `memory.pressure`. Builds run as transient scopes inside `builds.slice`,
  whose PSI is recorded for all of them together. Existing `jobs.slice`
  locations also receive slow pressure/accounting. Individual job scopes are
  sampled only if the holder/watch selection picks them; coverage of every
  job scope and the future slice arrangement remain outside this extension.
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

## Seven-day ordinary-operation measurement

For [#405](https://github.com/nisavid/dotfiles/issues/405), use the existing
recorder for seven consecutive days of ordinary work after the reviewed
extension is separately deployed. This procedure does not mean that deployment
or the seven-day window has started. Load this procedure before beginning
that measurement. Record the reviewed revision used, the measurement's start
and end in UTC, the recorder's source digest, and known workload or
configuration rollouts. Maintain a manual UTC
timeline of ordinary app/plugin updates, workload-cap changes, model/service
changes, and naturally reported stalls; record what is known without adding
command lines or credentials to the record. Keep unchanged-policy periods
separate, including changes to workload caps, plugin policy, and the
kernel. Missing representative work is a gap to report; do not manufacture
load or extend the study to fill it.

Read `samples/` rather than only `latest.json`. Within each boot and unchanged
policy period, calculate counter rates using the actual elapsed seconds. Skip
comparisons across a missing observation, counter decrease, recreated cgroup,
device replacement, or sampling gap. Keep each cgroup and each storage layer
separate: parent and child memory totals overlap, as do mapper, RAID, and
physical-device traffic. Swap slots describe occupancy, not physical writes;
`zswpwb` overlaps disk swap-out accounting. Anonymous/file and
direct/background scan categories also overlap and must not be added together.

Report daily minima, maxima, and percentiles, with aligned 60-second and
five-minute windows around naturally reported stalls and workload transitions.
Compare anonymous paging with file refaults, direct with background reclaim,
memory/I/O/CPU stall time, compressed with logical swapped bytes, swap-area
occupancy with device traffic, and group-local pressure/events with host
headroom. Include the recorder's CPU, RSS, cgroup memory, bytes written, and
tick lag. CPU pressure does not establish compression cost; file refaults do
not identify the refaulted files.

At seven days, classify each setting as **retain**, **candidate for a separately
approved comparison**, or **insufficient evidence**. Preserve the measurement
window and gaps with that result. This passive baseline selects no tuning
and cannot establish that an untested replacement performs better. Root-only
zswap, slab, fragmentation, and MGLRU diagnostics remain optional operator-provided
evidence; the recorder does not acquire privileges or mount debugfs.

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

Try it without the service: `memory-telemetry sample` prints one fast, one
slow, and one metadata object and writes nothing, and
`memory-telemetry run --state-dir "$(mktemp -d)" --duration 120` records for two
minutes into a new private scratch directory.

To turn it off, follow the comment at the top of
`home/dot_config/systemd/user/memory-telemetry.service`. The record stays until
deleted.
