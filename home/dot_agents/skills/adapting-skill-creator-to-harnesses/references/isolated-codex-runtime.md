# Isolated Codex trigger evaluation

Use the native or ACPX runner to measure actual implicit skill selection and
loading of a generated sentinel body. Treat candidate descriptions and queries
as untrusted instructions. Prompt wording and recorded tool diagnostics are
measurement controls; the container boundary protects credentials and the host.

## Build and run

Use a trusted local Docker-compatible engine with Linux containers, including
Docker Desktop on macOS. The engine and runtime image are trusted components.
Do not select an untrusted remote engine or substitute an unreviewed image.
Build from this skill's directory:

```sh
docker build --target runtime -f runtime/Dockerfile \
  -t nisavid-trigger-eval:codex-0.163.0-acpx-0.19.6 .
python3 scripts/codex_trigger_eval.py \
  --skill-dir /path/to/skill --workspace /path/to/results \
  --codex-home /path/to/authenticated/codex-home
```

Use `scripts/acpx_trigger_eval.py` for the ACPX path. Keep `--model`, `--effort`,
`--index`, `--limit`, and the result formats as before. `--codex-bin` and
`--acpx-bin` select executables **inside the image**, never on the host.
`--container-runtime` selects the engine executable and `--runtime-image`
selects a locally built compatible image. Images are never pulled automatically
when running a probe. The obsolete native `--sandbox` accepts only its original
`read-only` spelling; it cannot opt out of outer isolation.

Authenticate or refresh Codex outside the evaluator before running. The broker
accepts either an API key stored in `auth.json` or its ChatGPT access token and
account ID. It never receives the refresh token or copies authentication into
the evaluator. Keyring-only authentication and ambient API-key variables are
not imported. An expired token produces an authentication error; renew it with
the normal trusted Codex login workflow and retry. The evaluator never changes
the source authentication file.

## Enforcement boundary

Each probe creates a fresh evaluator container, broker container, and named
socket volume. The evaluator has no host mounts or external network interface.
It runs as an unprivileged user with all capabilities removed, no new
privileges, a read-only image, and bounded temporary home/work directories.
Only the generated skill and locked provider configuration are transferred.
The host's other skills, configuration, environment, and credentials are absent.

The broker receives the minimal credential over its standard input. It has
external network access, but the evaluator can reach it only through the Unix
socket. A loopback relay inside the evaluator supplies the Responses endpoint
expected by Codex. The broker admits only the Responses inference route to a
fixed HTTPS OpenAI or ChatGPT upstream; redirects, caller-selected destinations,
remote hosted tools, arbitrary headers, and upstream error bodies are rejected.
Requests and response sizes are bounded. A probe can consume inference within
those bounds; this is not an isolation mechanism for the selected model's cost.

Codex's inner mode permits shell execution **inside this outer boundary**.
This is necessary to read the skill body and avoids relying on ACPX's legacy
read-only policy or nested sandbox support. ACPX's after-the-fact diagnostics
still decide whether the probe obeyed the skill-reading measurement contract.
Shell access grants no host or broker filesystem/process access.

All three resources are removed after completion, exceptions, timeouts, and
catchable termination (SIGTERM, SIGINT, or SIGHUP). Both CLI runners use the
same main-thread controller. Termination during resource creation is deferred
until that engine operation finishes; repeated signals cannot interrupt cleanup.
SIGKILL, a controller crash, or host power loss cannot run Python cleanup;
remove any surviving `trigger-eval-*` containers and socket volumes before reuse.
Container teardown terminates descendants and ACP sessions. `--keep-probe-homes`
retains only host-side generated probe files, never a container home or auth.
If the engine becomes unavailable during cleanup, the runner reports the
resource names to remove; resolve that error before starting another evaluation.

## Verification

Run the regular skill suite and the explicit container integration gate:

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
docker build --target container-tests -f runtime/Dockerfile \
  -t nisavid-trigger-eval:codex-0.163.0-acpx-0.19.6-test .
TRIGGER_EVAL_CONTAINER_TESTS=1 python3 -m unittest discover \
  -s tests -p 'test_*.py'
```

The additional image includes only a test inference fixture. Integration tests use synthetic
credentials and deterministic inference fixtures, never real login state or
billable model calls. They exercise actual container reads, process visibility,
network access, and cleanup. Without an available engine, those tests cannot
establish isolation; an explicit container gate must fail rather than skip.
`--require-file-trace` remains an unsupported legacy diagnostic: host `strace`
availability does not establish container file-access evidence.
