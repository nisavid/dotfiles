"""Public synthetic artifacts captured from the Provingkit projector."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

FIXTURES = json.loads(
    (
        Path(__file__).parent / "fixtures/provingkit-installations/artifacts.json"
    ).read_text()
)
CATALOGS = {
    "agent-plugins": ".agents/plugins/marketplace.json",
    "claude": ".claude-plugin/marketplace.json",
    "cursor": ".cursor-plugin/marketplace.json",
}


def fixture_selection(
    home: Path, case: str = "a", clients: tuple[str, ...] = ("cursor",)
) -> dict:
    """Materialize exact captured files, then describe their local fixture URLs."""
    fixture = FIXTURES["cases"][case]
    profile = {
        "schema": "provingkit-installation-selection-v1",
        "platform": {"os": "linux", "arch": "amd64"},
        "adoption": {
            "stage": "preview" if case == "preview" else "ad_hoc",
            "identity": f"fixture-{case}",
            "record": "https://example.invalid/public-installer-fixture",
        },
        "source": {
            "repository": "https://github.com/nisavid/provingkit",
            "commit": fixture["source_commit"],
        },
        "artifact_slate": fixture["members"],
        "artifacts": {},
        "clients": {},
        "retirements": [],
    }
    published = home / "published" / case
    published.mkdir(parents=True, exist_ok=True)
    for client in clients:
        target = "agent-plugins" if client == "codex" else client
        data = fixture["targets"][target]
        artifact = (
            home
            / ".local/share/provingkit/artifacts"
            / target
            / data["artifact_sha256"]
        )
        artifact.mkdir(parents=True, exist_ok=True)
        for relative, text in data["files"].items():
            path = artifact / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            path.chmod(int(data["modes"].get(relative, "0644"), 8))
        evidence = (
            home / ".local/share/provingkit/evidence" / target / data["artifact_sha256"]
        )
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / "RECEIPT.json").write_text(data["files"]["RECEIPT.json"])
        (evidence / "modes.tsv").write_text(data["mode_manifest"])
        stem = f"fixture-{case}-{target}"
        archive = published / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            package.add(artifact, arcname=stem)
        receipt = published / f"{stem}.RECEIPT.json"
        receipt.write_text(data["files"]["RECEIPT.json"])
        modes = published / f"{stem}.modes.tsv"
        modes.write_text(data["mode_manifest"])
        profile["artifacts"][target] = {
            "archive": {
                "url": archive.as_uri(),
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                "root": stem,
            },
            "artifact_sha256": data["artifact_sha256"],
            "receipt": {"url": receipt.as_uri(), "sha256": data["receipt_sha256"]},
            "modes": {"url": modes.as_uri(), "sha256": data["modes_sha256"]},
            "catalog": CATALOGS[target],
        }
        profile["clients"][client] = {
            "artifact": target,
            "route": "user_local_directory"
            if client == "cursor"
            else "native_marketplace",
            "scope": "implicit_user" if client == "codex" else "user",
            "members": {member: {"enabled": True} for member in fixture["members"]},
        }
    return {
        "schema": "provingkit-installations-v1",
        "profile_name": "portable-linux",
        "host_platform": {"os": "linux", "arch": "amd64"},
        "profile": profile,
    }


def artifact_root(home: Path, selection: dict, target: str) -> Path:
    return (
        home
        / ".local/share/provingkit/artifacts"
        / target
        / selection["profile"]["artifacts"][target]["artifact_sha256"]
    )
