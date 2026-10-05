"""Public synthetic artifacts captured from the Provingkit projector."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
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
            "route": (
                "user_local_directory" if client == "cursor" else "native_marketplace"
            ),
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


def fixture_recovery_packet(base: Path) -> tuple[dict, Path, dict]:
    """Package captured ordinary artifacts and the documented Codex alias."""
    publisher = base / "publisher"
    ordinary = fixture_selection(publisher, "six_a", ("codex", "claude"))
    profile = ordinary["profile"]
    packet_files = {"RECOVER.md": b"Synthetic offline recovery fixture.\n"}
    manifest = {
        "schema": "provingkit-artifact-recovery-packet-v1",
        "version": "0.1.0-alpha.4",
        "source": profile["source"],
        "artifact_slate": profile["artifact_slate"],
        "targets": {},
    }
    canonical = artifact_root(publisher, ordinary, "agent-plugins")
    alias = publisher / "alias"
    shutil.copytree(canonical, alias)
    catalog_path = CATALOGS["agent-plugins"]
    catalog = (alias / catalog_path).read_bytes()
    (alias / catalog_path).write_bytes(
        catalog.replace(b'"name":"provingkit"', b'"name":"provingkit-local"', 1)
    )
    derivative = {
        "schema": "provingkit-local-marketplace-projection-v1",
        "source_commit": profile["source"]["commit"],
        "parent_receipt_sha256": hashlib.sha256(
            (canonical / "RECEIPT.json").read_bytes()
        ).hexdigest(),
        "change": {
            "path": catalog_path,
            "field": "name",
            "from": "provingkit",
            "to": "provingkit-local",
        },
        "plugin_slate": profile["artifact_slate"],
    }
    (alias / "RECEIPT.json").write_text(json.dumps(derivative, indent=2) + "\n")
    for target in ("agent-plugins", "agent-plugins-local", "claude"):
        root = (
            alias
            if target == "agent-plugins-local"
            else artifact_root(publisher, ordinary, target)
        )
        directories = {".": "0700"}
        for path in [root, *root.rglob("*")]:
            if path.is_dir():
                path.chmod(0o700)
                if path != root:
                    directories[path.relative_to(root).as_posix()] = "0700"
        (root / "RECEIPT.json").chmod(0o600)
        archive_path = f"artifacts/{target}.tar.gz"
        stream = io.BytesIO()

        def packet_member(item):
            item.mtime = 0
            item.pax_headers = {}
            return item

        with tarfile.open(fileobj=stream, mode="w:gz") as package:
            package.add(root, arcname=target, filter=packet_member)
        packet_files[archive_path] = stream.getvalue()
        receipt_path = f"receipts/{target}.json"
        packet_files[receipt_path] = (root / "RECEIPT.json").read_bytes()
        modes_path = f"modes/{target}.tsv"
        ordinary_target = "agent-plugins" if target == "agent-plugins-local" else target
        packet_files[modes_path] = FIXTURES["cases"]["six_a"]["targets"][
            ordinary_target
        ]["mode_manifest"].encode()
        tree = hashlib.sha256(b"provingkit-tree-v1\0")
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "RECEIPT.json":
                name = path.relative_to(root).as_posix().encode()
                data = path.read_bytes()
                tree.update(
                    len(name).to_bytes(8, "big")
                    + name
                    + len(data).to_bytes(8, "big")
                    + data
                )
        manifest["targets"][target] = {
            "kind": (
                "codex_local_alias" if target == "agent-plugins-local" else "ordinary"
            ),
            "archive": {
                "path": archive_path,
                "root": target,
                "sha256": hashlib.sha256(packet_files[archive_path]).hexdigest(),
            },
            "artifact_sha256": tree.hexdigest(),
            "catalog": CATALOGS[ordinary_target],
            "directories": directories,
            "receipt": {
                "path": receipt_path,
                "sha256": hashlib.sha256(packet_files[receipt_path]).hexdigest(),
            },
            "receipt_mode": "0600",
            "modes": {
                "path": modes_path,
                "sha256": hashlib.sha256(packet_files[modes_path]).hexdigest(),
            },
        }
    manifest["files"] = [
        {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(packet_files.items())
    ]
    packet_files["MANIFEST.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    packet = base / "recovery.tar.gz"
    with tarfile.open(packet, "w:gz") as package:
        for name, data in sorted(packet_files.items()):
            item = tarfile.TarInfo(name)
            item.size, item.mode = len(data), 0o600
            package.addfile(item, io.BytesIO(data))
    record = {
        "schema": "provingkit-recovery-selection-v1",
        "version": manifest["version"],
        "source": manifest["source"],
        "platform": {"os": "linux", "arch": "amd64"},
        "packet": {
            "bytes": packet.stat().st_size,
            "sha256": hashlib.sha256(packet.read_bytes()).hexdigest(),
        },
        "manifest_sha256": hashlib.sha256(packet_files["MANIFEST.json"]).hexdigest(),
        "intended_remote_path": "/my-files/Project Recovery/Provingkit/fixture.tar.gz",
        "retention": "keep-until-approved-retirement",
    }
    selection = {
        "schema": "provingkit-installations-v1",
        "profile_name": None,
        "profile": None,
        "host_platform": record["platform"],
        "recovery_packets": {"fixture": record},
    }
    return selection, packet, manifest
