"""Regenerate public synthetic artifacts with the frozen upstream projector."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--producer-source",
    type=Path,
    required=True,
    help="Local public Provingkit Git checkout",
)
arguments = parser.parse_args()
destination = Path(__file__).parent
members = ["proseweaving", "versionkeeping", "mergecraft"]
all_members = [
    "rolecasting",
    "tricritical",
    "versionkeeping",
    "mergecraft",
    "artifact-customs",
    "proseweaving",
]
result = {"producer_commit": "147e1ddfc969b5119001488ce1556627d3b2449b", "cases": {}}
# The projector copies its policy's owner address into the Claude and Cursor
# catalogs. The captured fixtures carry this synthetic address instead, and the
# receipt digests are recomputed to match.
SYNTHETIC_OWNER_EMAIL = "ivan@example.invalid"
CATALOGS = {
    "claude": ".claude-plugin/marketplace.json",
    "cursor": ".cursor-plugin/marketplace.json",
}


def compact_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def replace_owner_email(output, target):
    """Swap the catalog owner address and restore the receipt's digests."""
    catalog = CATALOGS.get(target)
    if catalog is None:
        return
    catalog_path = output / catalog
    catalog_data = json.loads(catalog_path.read_bytes())
    catalog_data["owner"]["email"] = SYNTHETIC_OWNER_EMAIL
    catalog_path.write_text(compact_json(catalog_data))
    receipt_path = output / "RECEIPT.json"
    receipt = json.loads(receipt_path.read_bytes())
    inventory = []
    tree = hashlib.sha256(b"provingkit-tree-v1\0")
    for name in sorted(
        p.relative_to(output).as_posix()
        for p in output.rglob("*")
        if p.is_file() and p.name != "RECEIPT.json"
    ):
        data = (output / name).read_bytes()
        inventory.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
        encoded = name.encode()
        tree.update(
            len(encoded).to_bytes(8, "big")
            + encoded
            + len(data).to_bytes(8, "big")
            + data
        )
    receipt["files"] = inventory
    receipt["artifact_sha256"] = tree.hexdigest()
    receipt_path.write_text(compact_json(receipt))


with tempfile.TemporaryDirectory(prefix="provingkit-public-fixture-") as temporary:
    root = Path(temporary)
    here = root / "projector"
    here.mkdir()
    for source_path, name in (
        ("scripts/build_release_artifacts.py", "build_release_artifacts.py"),
        ("release/artifact-projection-policy-v1.json", "policy.json"),
    ):
        content = subprocess.check_output(
            [
                "git",
                "-C",
                str(arguments.producer_source),
                "show",
                result["producer_commit"] + ":" + source_path,
            ]
        )
        (here / name).write_bytes(content)
    source = root / "source"
    source.mkdir()
    (source / "scripts").mkdir()
    (source / "scripts/build_release_artifacts.py").write_bytes(
        (here / "build_release_artifacts.py").read_bytes()
    )
    (source / "release").mkdir()
    (source / "release/artifact-projection-policy-v1.json").write_bytes(
        (here / "policy.json").read_bytes()
    )
    for name in all_members:
        plugin = source / "plugins" / name
        (plugin / "skills/fixture").mkdir(parents=True)
        manifest = {
            "name": name,
            "version": "1.0.0",
            "description": "Public synthetic installer fixture",
            "author": {"name": "Fixture"},
        }
        (plugin / "plugin.json").write_text(json.dumps(manifest) + "\n")
        (plugin / ".claude-plugin").mkdir()
        (plugin / ".claude-plugin/plugin.json").write_text(json.dumps(manifest) + "\n")
        (plugin / "skills/fixture/SKILL.md").write_text(
            "---\nname: fixture\ndescription: Synthetic installer fixture, not an agent workflow.\n---\n\nFixture A.\n"
        )
        (plugin / "skills/fixture/check.sh").write_text(
            '#!/bin/sh\nprintf "%s\\n" fixture\n'
        )
        (plugin / "skills/fixture/check.sh").chmod(0o755)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=source, check=True)
    environment = os.environ | {
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
    }
    for case in ["a", "six_a", "b", "preview"]:
        if case == "b":
            path = source / "plugins/proseweaving/skills/fixture/SKILL.md"
            path.write_text(path.read_text().replace("Fixture A.", "Fixture B."))
        if case == "preview":
            (source / "fixture-stage").write_text("whole-kit synthetic preview\n")
        subprocess.run(["git", "add", "."], cwd=source, check=True)
        if case != "six_a":
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "-qm",
                    f"fixture: {case}",
                ],
                cwd=source,
                check=True,
                env=environment,
            )
        selected = all_members if case in ("six_a", "preview") else members
        case_result = {"members": selected, "targets": {}}
        for target in ["agent-plugins", "claude", "cursor"]:
            output = root / f"{case}-{target}"
            subprocess.run(
                [
                    "python3",
                    "-B",
                    str(here / "build_release_artifacts.py"),
                    "--source",
                    str(source),
                    "--target",
                    target,
                    "--slate",
                    ",".join(selected),
                    "--output",
                    str(output),
                ],
                check=True,
                capture_output=True,
            )
            replace_owner_email(output, target)
            receipt_bytes = (output / "RECEIPT.json").read_bytes()
            receipt = json.loads(receipt_bytes)
            files = {
                p.relative_to(output).as_posix(): p.read_text()
                for p in sorted(output.rglob("*"))
                if p.is_file()
            }
            modes = {
                p.relative_to(output).as_posix(): format(
                    p.stat().st_mode & 0o777, "04o"
                )
                for p in sorted(output.rglob("*"))
                if p.is_file() and p.name != "RECEIPT.json"
            }
            mode_text = "path\tmode\torigin\n" + "".join(
                f"{p}\t{mode}\tpublic-fixture\n" for p, mode in modes.items()
            )
            case_result["source_commit"] = receipt["source"]["commit"]
            case_result["targets"][target] = {
                "files": files,
                "modes": modes,
                "mode_manifest": mode_text,
                "receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
                "modes_sha256": hashlib.sha256(mode_text.encode()).hexdigest(),
                "artifact_sha256": receipt["artifact_sha256"],
            }
        result["cases"][case] = case_result
destination.mkdir(parents=True, exist_ok=True)
(destination / "artifacts.json").write_text(json.dumps(result, indent=2) + "\n")
