# Proton Pass CLI 2.3.2 `run` contract

Research date: 2026-08-25

This note records the public contract and tagged implementation of Proton Pass
CLI 2.3.2 `run`. It supports the Wayfinder decision map in [Evaluate replacing
secret-exec with pass-cli
run](https://github.com/nisavid/dotfiles/issues/173); it does not decide whether
the repository should replace its secret data plane.

No provider command or behavioral canary was run for this research. The
findings come from official documentation, immutable tagged source and tests,
and release metadata. Host qualification remains separate.

Executable discovery is outside the upstream `run` contract. This map keeps
the settled repository rule: invoke `pass-cli` by command name through the
wrapped process's runtime `PATH`; do not recommend or encode a fixed path.

## Evidence boundary

Release 2.3.2 was published on 2026-08-14 for Linux x86-64 and ARM64, macOS
x86-64 and ARM64, and Windows x86-64. Its annotated tag
[`77417dc`](https://api.github.com/repos/ProtonPass/pass-cli/git/tags/77417dc50d9c51301cc0bfce6596ef940dda621c)
resolves to commit
[`11b0c8f`](https://github.com/ProtonPass/pass-cli/commit/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0).
The tag, current `main`, and latest release were identical on the research date.
The release immediately follows a 2.3.1 fix that restored separation of child
stdout and stderr; 2.3.2 itself is described as improving secret-reference
parsing without changing `run.rs` or its guide. See the [2.3.2 release](https://github.com/ProtonPass/pass-cli/releases/tag/2.3.2),
[tagged changelog](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/CHANGELOG.md#L8-L22),
[2.3.1-to-2.3.2 comparison](https://github.com/ProtonPass/pass-cli/compare/2.3.1...2.3.2),
and [2.3.2-to-`main`
comparison](https://github.com/ProtonPass/pass-cli/compare/2.3.2...main).

The [upstream GitHub repository](https://github.com/ProtonPass/pass-cli/issues)
has its issue tracker disabled. There is no upstream issue record to strengthen,
narrow, or contradict the tagged contract.

## Contract summary

| Surface | Documented claim | Tagged 2.3.2 behavior |
| --- | --- | --- |
| Environment sources | Inherit the current environment; later dotenv files override earlier files. | The source collects Unicode process variables first, then replaces matching names once per dotenv file in command-line order. Within one file, the last duplicate wins when the final map is built. |
| Dotenv syntax | Each line is `KEY=VALUE`. | A small custom parser trims the whole line, ignores blank and comment lines, splits at the first `=`, accepts ASCII shell-style names, trims the value, and removes one matching pair of outer single or double quotes. It does not implement general dotenv escaping, expansion, inline-comment, or multiline semantics. Invalid lines and names warn and are skipped; unreadable or non-UTF-8 files fail the command. |
| References | Scan values, substitute embedded references, and resolve multiple references in one value. | Discovery accepts a value only when it starts with `pass://` and the entire value parses as one item reference. Resolution therefore supports one whole-value reference per variable. Embedded and multiple references are not implemented. |
| Masking | Mask secret values in child stdout and stderr unless `--no-masking` is set. | Mask candidates are final values of variables recognized as whole-value references. A candidate is included only when the byte length of its regex-escaped representation is at least five. Output is decoded and rewritten one line at a time, even with `--no-masking`. |
| I/O | Forward stdin, stdout, and stderr; not a full TTY. | All three child streams are pipes. Stdin is copied in 1,024-byte chunks. Stdout and stderr are independently decoded as UTF-8 lines and re-emitted by two threads. The child never inherits terminal file descriptors or a pseudo-terminal. |
| Signals | Forward SIGTERM and SIGINT for graceful shutdown. | The explicit handler waits only for Ctrl+C. On Unix it sends SIGTERM to the direct child, waits two seconds, then sends SIGKILL if that PID still exists. On Windows it invokes `taskkill /PID ... /F`. The source has no `run` path that forwards wrapper SIGTERM. |
| Exit | Not specified beyond executing the command. | A normal numeric child exit code is passed to `process::exit`. A Unix child terminated by a signal has no numeric code, so the source substitutes `-1`, which becomes status 255 on Unix. The Ctrl+C path exits 130 after termination handling. |
| Descendants | Not specified. | The wrapper signals one child PID, not a process group or Windows process tree. It provides no descendant cleanup or orphan-prevention contract. Descendants can also inherit the injected environment. |
| Concurrency | Not specified. | Reference resolution is sequential within an invocation and has an invocation-local cache. Separate invocations are not serialized by `run`; shared session persistence uses atomic replacement and a process-local lock, but no interprocess lock or compare-and-swap. |

The documentation claims are in the official [`run`
guide](https://protonpass.github.io/pass-cli/commands/contents/run/) and its
[immutable source](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/docs/public/docs/commands/contents/run.md#L11-L32).
The implementation summary follows the tagged [`run.rs`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs)
and [`secret_resolver.rs`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/secret_resolver.rs).

## Dotenv and inherited environment

The parser reads each file as UTF-8 text. It trims every line before parsing,
skips blank lines and lines whose first non-whitespace character is `#`, and
splits a setting at its first `=`. Names must match the ASCII shape
`[A-Za-z_][A-Za-z0-9_]*`. Values are trimmed; matching outer single or double
quotes are stripped without interpreting their contents. An empty value,
including a matching empty quoted value, is retained. The source does not
recognize `export`, escape sequences, interpolation, inline comments, or
multiline values as separate dotenv features. See [`load_dotenv_file`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L47-L110)
and its [tagged tests](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L450-L481).

Process variables are collected before files. For every file, all earlier
entries whose names occur in that file are removed, then all entries from the
file are appended. Later files therefore override the process and earlier
files. The final `HashMap` insertion makes the last duplicate within one file
the child-visible value. An earlier duplicate containing a recognized
reference can nevertheless trigger a provider read even when a later plain
value wins; the name-based masking setup then treats that final plain value as
a mask candidate. This matches the documented inter-file precedence but leaves
duplicate-key behavior implicit. See
[`get_environment_variables`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L112-L137)
and [`merge_resolved_env`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L184-L199).

Collection uses `std::env::vars`, which accepts only Unicode names and values;
on Unix, a non-Unicode inherited variable can panic this path rather than pass
through. The child receives the resulting environment through
`Command::envs`. The calling shell is unchanged, but the environment is not
confined to one process in the stronger sense implied by the guide: ordinary
child descendants inherit it unless they clear or replace it, and the wrapper
does not supervise those descendants. See [environment collection](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L112-L137)
and [child creation](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L336-L364).

## Reference discovery and resolution

`find_pass_uri` does not scan. It checks `starts_with("pass://")`, parses the
whole string as one `ItemReference`, and returns that whole string. `run` keeps
at most one reference per environment-variable name and replaces that complete
string after resolving it. References in separate variables work, and repeated
references can use an invocation-local cache, but embedded or multiple
references in one variable do not follow the documented substitution model.
The upstream unit test explicitly expects a mixed-text value not to be
detected. See [`find_pass_uri`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/secret_resolver.rs#L311-L318),
[discovery and replacement](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L139-L181),
and the [discovery test](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L483-L514).

This discrepancy also changes failure behavior. A value that merely contains a
reference, or starts like one but fails `ItemReference` parsing, is left
literal and does not fail closed. A discovered item reference that lacks the
field required by `SecretReference` fails before the child starts. Resolution
is sequential; a missing item, missing field, monitor failure, or provider
failure stops the command before process creation. See [`SecretReference::parse`
and resolution](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/secret_resolver.rs#L184-L260)
and the [`run` sequence](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L413-L444).

## Masking and output fidelity

The default masking regex is built from the final value of every variable whose
original value was recognized as a reference. It escapes each value for regex
use, then includes it only if that escaped UTF-8 string is at least five bytes.
This is not a character-count guarantee: ordinary short values are omitted,
while regex punctuation and multibyte characters alter the threshold. Empty
values are omitted. See [`create_masking_regex`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L201-L234).

Mask candidates come from `HashMap` iteration and are joined directly as regex
alternatives. The source does not sort overlapping values longest-first.
Complete masking of prefix-overlapping values is therefore not guaranteed by
the implementation and requires a behavioral canary. A candidate containing a
newline also cannot match across the line-processing boundary. The tagged tests
cover multiple occurrences and dotenv-only candidates, but not short,
multibyte, multiline, or overlapping values. See the [masking tests](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L516-L537)
and [dotenv-only regression test](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L607-L641).

Both output streams are always piped through `BufReader::lines` and emitted
with `println!` or `eprintln!`. Consequently, the wrapper:

- waits for a line ending or EOF before emitting a partial line;
- removes input line terminators and adds a new terminator, including after a
  final unterminated line;
- rejects non-UTF-8 output as a read error rather than forwarding its bytes;
- loses child write boundaries and does not preserve ordering between the two
  independently handled streams; and
- applies all of those transformations even when `--no-masking` disables only
  regex replacement.

This is a text-line filter, not byte-preserving forwarding. See
[`handle_stream`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L279-L307)
and [stream setup](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L356-L376).

## I/O, exit, signals, and descendants

The documentation explicitly limits `run` to scripts and non-interactive
programs. The source pipes all three streams, copies stdin bytes in 1,024-byte
chunks, and decodes output as lines. A child therefore does not receive a TTY
or pseudo-terminal. Basic stdin can pass through, but terminal detection, job
control, terminal sizing, and full-screen interaction are outside the contract;
a prompt without a newline can remain buffered until a newline or EOF.
See the [interactive-program limitation](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/docs/public/docs/commands/contents/run.md#L137-L147)
and [`handle_stdin`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L309-L334).

Normal child completion is waited and its numeric status is passed to
`process::exit` after both output threads join. On Unix, signal termination
produces no numeric status; the source substitutes `-1`, which the Unix exit
API exposes as 255. No source test covers either path. See
[`execute_command`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L336-L411).

The source's explicit signal behavior is narrower than the guide:

- `tokio::signal::ctrl_c` is the only selected signal future;
- on Linux and macOS, that path sends SIGTERM—not SIGINT—to the direct child,
  waits two seconds, and sends SIGKILL if the PID still exists;
- on Windows, it runs `taskkill` with `/PID` and `/F`, without `/T`;
- it exits 130 immediately after that helper returns, without joining the
  stdout and stderr threads; and
- there is no wrapper-SIGTERM forwarding path, process-group signal, child-tree
  kill, configurable timeout, or general orphan prevention.

On normal direct-child exit, `run` joins its output threads before returning.
A surviving descendant that retained an inherited output pipe can therefore
delay EOF and keep the wrapper waiting even after the direct child exits.

A terminal may independently deliver a foreground signal to multiple members
of its process group; that operating-system effect is not the forwarding
contract implemented here and remains a canary question. See [platform kill
helpers](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L246-L277)
and [Ctrl+C selection](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L378-L410).

## Failure and concurrency matrix

| Condition | Tagged behavior before a behavioral canary |
| --- | --- |
| Unauthenticated or unusable session | The top-level command requires an authenticated client before dispatching `run`; it exits with an error instead of spawning the child. An invalidated session takes the CLI's logout-and-exit-1 path. |
| Locked session | Official session documentation says API operations are rejected while locked. `run` has no unlock or retry branch; a reference-resolution request propagates that failure and does not spawn the child. |
| Expired agent or personal-access-token session | Official docs assign these sessions a two-hour lifetime. `run` provides no renewal path; authentication or resolution failure prevents child creation. |
| Agent session without a reason | `run` validates `PROTON_PASS_AGENT_REASON` before reading its environment files. A missing, empty, or overlong reason fails without a child. |
| Missing, unreadable, or non-UTF-8 dotenv file | Fatal before reference discovery or child creation. |
| Invalid dotenv line or variable name | Warning to wrapper stderr; entry is skipped and execution continues. |
| Embedded, multiple, or parser-rejected reference | Not discovered; the literal value reaches the child. |
| Discovered malformed reference, missing item or field, locked session, or unavailable provider | Resolution error; no child is created, although provider reads for earlier variables may already have occurred. |
| Command missing or not executable | References are resolved first; spawn then fails and the CLI returns an error. |
| Child output is non-UTF-8 | The stream thread reports a decode/read error; byte-for-byte output is not preserved. |
| Child exits normally | Numeric status is propagated after output threads join. |
| Child exits by Unix signal | Status becomes 255 rather than the shell convention `128 + signal`. |
| Wrapper receives Ctrl+C | Direct-child termination path, two-second Unix grace, wrapper status 130; descendants are not supervised. |
| Wrapper receives SIGTERM | No explicit forwarding path in `run`; direct-child and descendant cleanup are not guaranteed. |
| Concurrent references in one invocation | Resolution is sequential; identical references can use the invocation-local cache. |
| Concurrent CLI invocations | No `run`-level coordination. Session writes use unique temporary names and atomic replacement, but their mutex and generation counter are process-local, so the source supplies no cross-process ordering guarantee. |

The invocation-local `run` cache joins decoded share, item, field, and TOTP
components with colons to form a string key. Distinct decoded component tuples
can therefore collide and cause a later reference to reuse an earlier cached
value. Release 2.3.2 changed `inject` to a structured key and added collision
regressions, but left `run` on the joined key. See [`SecretCache`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/secret_resolver.rs#L263-L309)
and the structured [`inject` cache](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/inject.rs#L150-L216).

Authentication dispatch is in [`main.rs`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/main.rs#L256-L373).
Agent-reason validation is in [`agent_monitor.rs`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/item/agent_monitor.rs#L25-L63).
The [session-lock guide](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/docs/public/docs/commands/session.md#L13-L18)
and [agent-session guide](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/docs/public/docs/commands/agent.md#L3-L8)
own those lifecycle claims. Cross-process persistence bounds follow
[`FileSystemSessionStorage`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/storage/session_storage.rs#L48-L116)
and the process-local [persistence lock](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-auth/src/store.rs#L168-L220).

## Tagged test coverage and unresolved observations

The 2.3.2 `run` unit tests cover basic comments and quoting, ASCII variable-name
validation, warning-and-skip handling for invalid names, whole-value reference
discovery, non-secret environment preservation, repeated masking within a
line, dotenv-only mask candidates, and one-character quote edge cases. They do
not cover:

- file or duplicate-key precedence;
- embedded or multiple references;
- distinct references whose decoded cache-key components collide;
- malformed references that escape discovery;
- short, multibyte, newline-containing, or overlapping resolved values;
- partial writes, final unterminated lines, binary output, line endings, or
  stdout/stderr ordering;
- TTY behavior;
- normal and signal exit propagation;
- SIGINT, SIGTERM, escalation, descendants, or orphan prevention;
- provider/session failure classes;
- concurrent invocations; or
- Linux/macOS/Windows behavioral parity.

The complete tagged test module is in
[`run.rs`](https://github.com/ProtonPass/pass-cli/blob/11b0c8f8fcc28fcbdb15c3d815dd1a4ae0a61ac0/pass-cli/src/commands/run.rs#L446-L682).
These omissions are evidence boundaries, not claims that every untested case
fails.

## Decision inputs

For 2.3.2, the narrow source-defined `run` contract is:

1. authenticated execution with inherited Unicode environment variables and
   ordered, simply parsed dotenv overrides;
2. one whole-value `pass://` reference per variable, resolved sequentially;
3. pipe-based, non-TTY execution;
4. optional regex replacement over line-decoded text output, not transparent
   byte forwarding;
5. normal numeric exit-code propagation, but no signal-faithful Unix status;
   and
6. Ctrl+C handling for one direct child, without a descendant-cleanup or
   concurrent-invocation guarantee.

Embedded and multiple references, unconditional masking, byte and line
fidelity, documented SIGTERM/SIGINT forwarding, signal-faithful exit, and
descendant cleanup must not be attributed to the 2.3.2 implementation. The
separate host-qualification tickets should verify the source-derived behavior
with disposable canaries; replacement acceptance and security policy remain
later Wayfinder decisions.
