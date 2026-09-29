from __future__ import annotations

import base64
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

# Import the harness modules, not their TestCase classes, so this module does
# not rerun their tests.
from tests import test_age_admission_provisioning as provisioning
from tests import test_age_admission_recovery_preimage as recovery_preimage

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs/secret-injection/PROTON_PASS_AGE_ADMISSION.md"
QUALIFY_SECTION = "## Qualify provider behavior and provision the signer"
RECOVER_SECTION = "## Recover trust when the current private signer is lost"
STAGE_COLLECTOR_SECTION = "### Stage the reviewed recovery collector"
REVALIDATE_SECTION = "### Revalidate the administrative preimage"
APPLY_SECTION = "### Apply one exception, merge, and restore"
PROVISIONER_SOURCE = "scripts/provision-age-admission-signer"
COLLECTOR_SOURCE = "scripts/prepare-age-admission-recovery-preimage"
SIGNERS_PATH = ".github/age-admission/allowed_signers"
SIGNERS_PREFIX = b'repository-owner namespaces="nisavid/dotfiles/age-admission/v1" '
DISPOSITION_REJECTED = b"production ready-for-recovery disposition is invalid\n"
BLOCK_COMPLETE = b"procedure block complete\n"
STAGING_TOOLS = ("awk", "chmod", "git", "mkdir", "mv", "stat")
HANDOFF_TOOLS = ("awk", "git", "ssh-keygen", "stat")
COMMIT_IDENTITY = (
    "-c",
    "user.name=Synthetic Procedure",
    "-c",
    "user.email=fixture@example.invalid",
    "-c",
    "commit.gpgsign=false",
)
ManifestOverrides = dict[str, dict[str, str]]

canonical_json = provisioning.canonical_json
run_git = provisioning.run_git
sha256 = provisioning.sha256


def runbook_zsh_block(section: str, end: str, anchor: str) -> str:
    lines = RUNBOOK.read_text(encoding="utf-8").splitlines()
    start = lines.index(section)
    stop = lines.index(end, start + 1)
    blocks: list[str] = []
    index = start + 1
    while index < stop:
        if lines[index] != "```zsh":
            index += 1
            continue
        close = lines.index("```", index + 1, stop)
        blocks.append("\n".join(lines[index + 1 : close]) + "\n")
        index = close + 1
    matches = [block for block in blocks if anchor in block]
    if len(matches) != 1:
        raise AssertionError(f"expected one runbook zsh block with {anchor!r}")
    return matches[0]


def provisioner_staging_script() -> str:
    run_commands = runbook_zsh_block(
        QUALIFY_SECTION, RECOVER_SECTION, f"{PROVISIONER_SOURCE} start"
    )
    start_command = run_commands.split("\n\n", 1)[0]
    if start_command.count("REQUEST.json") != 1 or start_command.count("NEW_DIR") != 1:
        raise AssertionError("the provisioner start command changed shape")
    start_command = start_command.replace(
        "REQUEST.json", '"$PROVISIONING_REQUEST"'
    ).replace("NEW_DIR", '"$PROVISIONING_STATE_DIRECTORY"')
    # The runbook issues the start command from the staging root.
    return (
        runbook_zsh_block(
            QUALIFY_SECTION, RECOVER_SECTION, ': "${PROVISIONING_STAGING_ROOT:?'
        )
        + 'cd -- "$PROVISIONING_STAGING_ROOT"\n'
        + start_command
        + "\n"
    )


def collector_staging_script() -> str:
    return runbook_zsh_block(
        STAGE_COLLECTOR_SECTION,
        REVALIDATE_SECTION,
        ': "${RECOVERY_COLLECTOR_STAGING:?',
    ) + runbook_zsh_block(
        REVALIDATE_SECTION, APPLY_SECTION, ': "${RECOVERY_PREIMAGE_COLLECTOR:?'
    )


def signers_handoff_script() -> str:
    return runbook_zsh_block(
        RECOVER_SECTION, STAGE_COLLECTOR_SECTION, ': "${PROVISIONING_STATE_DIR:?'
    )


def ed25519_public_key(first_byte: int) -> bytes:
    algorithm = b"ssh-ed25519"
    key = bytes((first_byte + offset) % 256 for offset in range(32))
    blob = (
        struct.pack(">I", len(algorithm))
        + algorithm
        + struct.pack(">I", len(key))
        + key
    )
    return b"ssh-ed25519 " + base64.b64encode(blob) + b" issue286-age-admission\n"


def allowed_signers_record(public_key: bytes) -> bytes:
    key_type, key_blob = public_key.split(b" ")[:2]
    return SIGNERS_PREFIX + key_type + b" " + key_blob + b"\n"


def rewrite_committed_checks(state_directory: Path, **checks: bool) -> None:
    """Change marker checks and re-derive every digest that binds them."""
    state_path = state_directory / "state.json"
    marker_path = state_directory / "ready-for-recovery.json"
    record_path = state_directory / "terminal-commit.json"
    state = json.loads(state_path.read_bytes())
    marker = json.loads(marker_path.read_bytes())
    record = json.loads(record_path.read_bytes())
    state["checks"].update(checks)
    marker["checks"] = state["checks"]
    marker_bytes = canonical_json(marker)
    plan = state["terminal_plan"]
    plan["marker"]["sha256"] = sha256(marker_bytes)
    record["marker"] = plan["marker"]
    record_bytes = canonical_json(record)
    plan["commit_record"]["sha256"] = sha256(record_bytes)
    marker_path.write_bytes(marker_bytes)
    record_path.write_bytes(record_bytes)
    state_path.write_bytes(canonical_json(state))


class ReviewedSource:
    """A disposable reviewed object database and its source manifest."""

    def __init__(
        self,
        root: Path,
        blobs: dict[str, bytes],
        modes: dict[str, str] | None = None,
    ) -> None:
        root.mkdir(mode=0o700)
        self.repository = root / "reviewed-source"
        self.repository.mkdir(mode=0o700)
        self.manifest = root / "reviewed-source-manifest.json"
        self.blobs = {
            relative: blobs.get(
                relative, provisioning.ProvisioningInputs.peer_stub(relative)
            )
            for relative in provisioning.SOURCE_MODES
        }
        requested = {**provisioning.SOURCE_MODES, **(modes or {})}
        run_git(self.repository, "init", "--quiet")
        for relative, data in self.blobs.items():
            destination = self.repository / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(data)
        run_git(self.repository, "add", "--all")
        for flag, executable in (("+x", True), ("-x", False)):
            selected = [
                relative
                for relative, mode in requested.items()
                if (mode == "100755") is executable
            ]
            run_git(self.repository, "update-index", f"--chmod={flag}", "--", *selected)
        run_git(
            self.repository,
            *COMMIT_IDENTITY,
            "commit",
            "--quiet",
            "-m",
            "synthetic reviewed source",
        )
        self.commit = (
            run_git(self.repository, "rev-parse", "HEAD").stdout.decode().strip()
        )
        tree_modes: dict[str, str] = {}
        listing = run_git(self.repository, "ls-tree", "-r", self.commit).stdout
        for line in listing.decode("ascii").splitlines():
            metadata, relative = line.split("\t", 1)
            tree_modes[relative] = metadata.split(" ", 1)[0]
        self.entries = [
            {
                "mode": tree_modes[relative],
                "path": relative,
                "sha256": sha256(self.blobs[relative]),
            }
            for relative in sorted(self.blobs)
        ]

    def manifest_bytes(self, overrides: ManifestOverrides | None = None) -> bytes:
        changes = overrides or {}
        return canonical_json(
            {
                "commit": self.commit,
                "entries": [
                    {**entry, **changes.get(str(entry["path"]), {})}
                    for entry in self.entries
                ],
                "schema": "issue286-reviewed-source-manifest/v1",
            }
        )

    def write_manifest(self, overrides: ManifestOverrides | None = None) -> str:
        data = self.manifest_bytes(overrides)
        self.manifest.write_bytes(data)
        self.manifest.chmod(0o600)
        return sha256(data)


class RecoveryCandidate:
    """A disposable recovery checkout whose commits vary only the signer file."""

    def __init__(self, path: Path) -> None:
        path.mkdir(mode=0o700)
        self.path = path
        run_git(path, "init", "--quiet")

    def commit(self, content: bytes, mode: str = "100644") -> str:
        target = self.path / SIGNERS_PATH
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(content)
        run_git(self.path, "add", "--", SIGNERS_PATH)
        flag = "+x" if mode == "100755" else "-x"
        run_git(self.path, "update-index", f"--chmod={flag}", "--", SIGNERS_PATH)
        run_git(
            self.path,
            *COMMIT_IDENTITY,
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "recovery candidate",
        )
        return run_git(self.path, "rev-parse", "HEAD").stdout.decode().strip()


class AgeAdmissionProcedureTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="age-admission-procedure.")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(strict=True)
        self.root.chmod(0o700)
        zsh = shutil.which("zsh")
        if zsh is None:
            self.fail("required tool is unavailable: zsh")
        self.zsh = Path(zsh).resolve(strict=True)

    def install_tools(self, name: str, commands: tuple[str, ...]) -> Path:
        directory = self.root / name
        directory.mkdir(mode=0o700)
        for command in commands:
            located = shutil.which(command)
            if located is None:
                self.fail(f"required tool is unavailable: {command}")
            (directory / command).symlink_to(Path(located).resolve(strict=True))
        for command in ("shasum", "sha256sum"):
            located = shutil.which(command)
            if located is not None:
                (directory / command).symlink_to(Path(located).resolve(strict=True))
                break
        else:
            self.fail("required SHA-256 tool is unavailable")
        (directory / "python3").symlink_to(Path(sys.executable).resolve(strict=True))
        return directory

    def base_environment(self, *search_path: Path) -> dict[str, str]:
        home = self.root / "home"
        home.mkdir(mode=0o700, exist_ok=True)
        return {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": os.fspath(home),
            "LC_ALL": "C",
            "PATH": os.pathsep.join(os.fspath(directory) for directory in search_path),
        }

    def run_zsh(
        self, name: str, script: str, environment: dict[str, str]
    ) -> subprocess.CompletedProcess[bytes]:
        path = self.root / f"{name}.zsh"
        path.write_text(
            script + "print -r -- 'procedure block complete'\n", encoding="utf-8"
        )
        return subprocess.run(
            [os.fspath(self.zsh), "-f", os.fspath(path)],
            capture_output=True,
            check=False,
            cwd=self.root,
            env=environment,
            timeout=90,
        )

    def recovery_fixture(self) -> recovery_preimage.RecoveryPreimageTests:
        # Reuse the recovery tests' fake GitHub and closed support path.
        fixture = recovery_preimage.RecoveryPreimageTests(
            "test_harness_uses_a_physical_root_and_closed_support_path"
        )
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        return fixture

    def test_staged_provisioner_passes_its_reviewed_self_binding(self) -> None:
        root = self.root / "provisioning"
        root.mkdir(mode=0o700)
        inputs = provisioning.ProvisioningInputs(root)
        staging = root / "provisioning-staging"
        tools = self.install_tools("staging-tools", STAGING_TOOLS)
        environment = inputs.environment()
        environment["PATH"] = os.pathsep.join((environment["PATH"], os.fspath(tools)))
        environment.update(
            {
                "PROVISIONING_REQUEST": os.fspath(inputs.request),
                "PROVISIONING_STAGING_ROOT": os.fspath(staging),
                "PROVISIONING_STATE_DIRECTORY": os.fspath(inputs.state),
                "REVIEWED_SOURCE_COMMIT": inputs.commit,
                "REVIEWED_SOURCE_MANIFEST": os.fspath(inputs.manifest),
                "REVIEWED_SOURCE_MANIFEST_SHA256": sha256(inputs.manifest.read_bytes()),
                "REVIEWED_SOURCE_REPOSITORY": os.fspath(inputs.source),
            }
        )

        result = self.run_zsh(
            "staged-provisioner", provisioner_staging_script(), environment
        )

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, b"qualified-clean\n" + BLOCK_COMPLETE, b""),
        )
        staged = staging / PROVISIONER_SOURCE
        self.assertEqual(os.listdir(staged.parent), [staged.name])
        self.assertEqual(stat.S_IMODE(staged.lstat().st_mode), 0o755)
        self.assertEqual(staged.read_bytes(), provisioning.PROVISIONER.read_bytes())
        state = json.loads((inputs.state / "state.json").read_bytes())
        self.assertEqual(state["outcome"], "qualified-clean")

    def test_staged_collector_runs_under_its_reviewed_manifest_digest(self) -> None:
        fixture = self.recovery_fixture()
        collector = recovery_preimage.COLLECTOR.read_bytes()
        source = ReviewedSource(self.root / "collector", {COLLECTOR_SOURCE: collector})
        manifest_sha256 = source.write_manifest()
        pull = fixture._fixture_value()
        pull["commits"] = [
            {"sha": source.commit},
            {"sha": recovery_preimage.HEAD_COMMIT},
        ]
        fixture.fixture.write_bytes(recovery_preimage._json_bytes(pull))
        staging = self.root / "collector-staging"
        private = self.root / "preimage-private"
        private.mkdir(mode=0o700)
        tools = self.install_tools("staging-tools", STAGING_TOOLS)
        environment = fixture._environment()
        environment.update(
            self.base_environment(fixture.bin, fixture.support_bin, tools)
        )
        environment.update(
            {
                "RECOVERY_BASE": recovery_preimage.BASE_COMMIT,
                "RECOVERY_COLLECTOR_STAGING": os.fspath(staging),
                "RECOVERY_HEAD": recovery_preimage.HEAD_COMMIT,
                "RECOVERY_PR_NUMBER": "286",
                "RECOVERY_PREIMAGE_PRIVATE_PARENT": os.fspath(private),
                "RECOVERY_REVIEWED_SOURCE": source.commit,
                "REVIEWED_SOURCE_MANIFEST": os.fspath(source.manifest),
                "REVIEWED_SOURCE_MANIFEST_SHA256": manifest_sha256,
                "REVIEWED_SOURCE_REPOSITORY": os.fspath(source.repository),
            }
        )

        result = self.run_zsh("staged-collector", collector_staging_script(), environment)

        self.assertEqual(
            (result.returncode, result.stdout, result.stderr),
            (0, BLOCK_COMPLETE, b""),
        )
        staged = staging / Path(COLLECTOR_SOURCE).name
        self.assertEqual(os.listdir(staging), [staged.name])
        self.assertEqual(stat.S_IMODE(staging.lstat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(staged.lstat().st_mode), 0o600)
        ready = json.loads((private / "initial/ready.json").read_bytes())
        self.assertEqual(ready["collector_sha256"], sha256(collector))
        self.assertEqual(ready["binding"]["reviewed_source_commit"], source.commit)
        self.assertEqual(
            ready["binding"]["trusted_reviewers"], recovery_preimage.TRUSTED_REVIEWERS
        )

    def test_unreviewed_staging_input_fails_before_execution(self) -> None:
        reviewed_provisioner = sha256(provisioning.PROVISIONER.read_bytes())
        reviewed_collector = sha256(recovery_preimage.COLLECTOR.read_bytes())
        # Each case: staged path, repository modes, manifest overrides, and the
        # overrides of the manifest whose digest the handoff pins (None: same).
        cases: dict[
            str, tuple[str, dict[str, str], ManifestOverrides, ManifestOverrides | None]
        ] = {
            "provisioner-tampered-blob": (
                PROVISIONER_SOURCE,
                {},
                {PROVISIONER_SOURCE: {"sha256": reviewed_provisioner}},
                None,
            ),
            "collector-tampered-blob": (
                COLLECTOR_SOURCE,
                {},
                {COLLECTOR_SOURCE: {"sha256": reviewed_collector}},
                None,
            ),
            "collector-substituted-manifest": (
                COLLECTOR_SOURCE,
                {},
                {},
                {COLLECTOR_SOURCE: {"sha256": reviewed_collector}},
            ),
            "collector-mode-mismatch": (
                COLLECTOR_SOURCE,
                {COLLECTOR_SOURCE: "100644"},
                {COLLECTOR_SOURCE: {"mode": "100755"}},
                None,
            ),
        }
        tools = self.install_tools("staging-tools", STAGING_TOOLS)
        for name, (target, modes, written, pinned) in cases.items():
            with self.subTest(name):
                case = self.root / name
                marker = case / "unreviewed-bytes-ran"
                unreviewed = (
                    "from pathlib import Path\n"
                    f"Path({os.fspath(marker)!r}).write_bytes(b'ran\\n')\n"
                ).encode("utf-8")
                source = ReviewedSource(case, {target: unreviewed}, modes)
                manifest_sha256 = source.write_manifest(written)
                if pinned is not None:
                    manifest_sha256 = sha256(source.manifest_bytes(pinned))
                staging = case / "staging"
                environment = self.base_environment(tools)
                environment.update(
                    {
                        "REVIEWED_SOURCE_MANIFEST": os.fspath(source.manifest),
                        "REVIEWED_SOURCE_MANIFEST_SHA256": manifest_sha256,
                        "REVIEWED_SOURCE_REPOSITORY": os.fspath(source.repository),
                    }
                )
                if target == PROVISIONER_SOURCE:
                    run_path = staging / PROVISIONER_SOURCE
                    script = provisioner_staging_script()
                    environment.update(
                        {
                            "PROVISIONING_REQUEST": os.fspath(case / "request.json"),
                            "PROVISIONING_STAGING_ROOT": os.fspath(staging),
                            "PROVISIONING_STATE_DIRECTORY": os.fspath(case / "state"),
                            "REVIEWED_SOURCE_COMMIT": source.commit,
                        }
                    )
                else:
                    run_path = staging / Path(COLLECTOR_SOURCE).name
                    script = collector_staging_script()
                    private = case / "private"
                    private.mkdir(mode=0o700)
                    environment.update(
                        {
                            "RECOVERY_BASE": recovery_preimage.BASE_COMMIT,
                            "RECOVERY_COLLECTOR_STAGING": os.fspath(staging),
                            "RECOVERY_HEAD": recovery_preimage.HEAD_COMMIT,
                            "RECOVERY_PR_NUMBER": "286",
                            "RECOVERY_PREIMAGE_PRIVATE_PARENT": os.fspath(private),
                            "RECOVERY_REVIEWED_SOURCE": source.commit,
                        }
                    )

                result = self.run_zsh(name, script, environment)

                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr), (1, b"", b"")
                )
                self.assertFalse(marker.exists())
                self.assertFalse(run_path.exists())

    def test_allowed_signers_handoff_binds_the_committed_production_key(self) -> None:
        root = self.root / "provisioning"
        root.mkdir(mode=0o700)
        inputs = provisioning.ProvisioningInputs(root)
        inputs.request_document["qualification"] = "live-disposable-provider"
        inputs.rewrite_request()
        qualified = inputs.run()
        self.assertEqual(qualified.returncode, 0, qualified.stderr)
        evidence = {
            key: {
                "path": os.fspath(inputs.state / name),
                "sha256": sha256((inputs.state / name).read_bytes()),
            }
            for key, name in (
                ("commit_record", "terminal-commit.json"),
                ("marker", "qualified-clean.json"),
                ("producer_state", "state.json"),
            )
        }
        inputs.state = inputs.private / "production-operation"
        inputs.request = inputs.private / "production-request.json"
        inputs._write_request(
            mode="production", qualification=None, qualified_clean=evidence
        )
        production = inputs.run()
        self.assertEqual(
            (production.returncode, production.stdout, production.stderr),
            (0, b"ready-for-recovery\n", b""),
        )

        public_key = (inputs.state / "private/admission-ed25519.pub").read_bytes()
        replacement_key = ed25519_public_key(0x80)
        record = allowed_signers_record(public_key)
        candidate = RecoveryCandidate(self.root / "recovery-candidate")
        heads = {
            "valid": candidate.commit(record),
            "replacement": candidate.commit(allowed_signers_record(replacement_key)),
            "extra-bytes": candidate.commit(b"# recovery signer\n" + record),
            "executable": candidate.commit(record, "100755"),
        }
        tools = self.install_tools("handoff-tools", HANDOFF_TOOLS)
        copies = self.root / "handoff-states"
        copies.mkdir(mode=0o700)
        public_relative = "private/admission-ed25519.pub"

        def verify(
            name: str,
            head: str,
            signer: bytes,
            mutate: Callable[[Path], None] | None,
        ) -> subprocess.CompletedProcess[bytes]:
            state = copies / name
            shutil.copytree(inputs.state, state, symlinks=True)
            if mutate is not None:
                mutate(state)
            environment = self.base_environment(tools)
            environment.update(
                {
                    "NEW_SIGNER_FINGERPRINT": provisioning.ssh_public_key_fingerprint(
                        signer
                    ),
                    "PROVISIONING_STATE_DIR": os.fspath(state),
                    "RECOVERY_CHECKOUT": os.fspath(candidate.path),
                    "RECOVERY_HEAD": heads[head],
                }
            )
            return self.run_zsh(f"handoff-{name}", signers_handoff_script(), environment)

        def replace_public_key(state: Path) -> None:
            (state / public_relative).write_bytes(replacement_key)

        def loosen_public_key(state: Path) -> None:
            (state / public_relative).chmod(0o644)

        def tamper_marker(state: Path) -> None:
            path = state / "ready-for-recovery.json"
            marker = json.loads(path.read_bytes())
            marker["authority"]["github_mutation_permitted"] = True
            path.write_bytes(canonical_json(marker))

        def fail_primary_readback(state: Path) -> None:
            rewrite_committed_checks(state, primary_readback=False)

        valid = verify("valid", "valid", public_key, None)

        self.assertEqual(
            (valid.returncode, valid.stdout, valid.stderr), (0, BLOCK_COMPLETE, b"")
        )
        # Each case: candidate head, accepted signer, state change, and stderr.
        rejected: dict[
            str, tuple[str, bytes, Callable[[Path], None] | None, bytes]
        ] = {
            "changed-public-key": (
                "replacement",
                replacement_key,
                replace_public_key,
                b"",
            ),
            "public-key-mode": ("valid", public_key, loosen_public_key, b""),
            "candidate-extra-bytes": ("extra-bytes", public_key, None, b""),
            "candidate-executable-mode": ("executable", public_key, None, b""),
            "tampered-marker": (
                "valid",
                public_key,
                tamper_marker,
                DISPOSITION_REJECTED,
            ),
            "false-primary-readback": (
                "valid",
                public_key,
                fail_primary_readback,
                DISPOSITION_REJECTED,
            ),
        }
        for name, (head, signer, mutate, stderr) in rejected.items():
            with self.subTest(name):
                result = verify(name, head, signer, mutate)

                self.assertEqual(
                    (result.returncode, result.stdout, result.stderr), (1, b"", stderr)
                )


if __name__ == "__main__":
    unittest.main()
