from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "home/private_dot_local/lib/hindsight-runtime/sitecustomize.py"
SPEC = importlib.util.spec_from_file_location("hindsight_sitecustomize", SOURCE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HindsightProviderBindingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reads_the_same_protected_descriptor_it_validates(self) -> None:
        path = self.root / "policy.json"
        path.write_bytes(b'{"schema_version":1}')
        path.chmod(0o600)

        self.assertEqual(
            MODULE._read_protected_file(path, "policy"),
            b'{"schema_version":1}',
        )
        path.chmod(0o640)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(path, "policy")

    def test_rejects_symlinks_and_multiple_hard_links(self) -> None:
        path = self.root / "auth.json"
        path.write_bytes(b"{}")
        path.chmod(0o600)
        link = self.root / "auth-link.json"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            MODULE._read_protected_file(link, "auth")

        hardlink = self.root / "auth-hardlink.json"
        os.link(path, hardlink)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(path, "auth")

    def test_rejects_writable_release_directories(self) -> None:
        release = self.root / "release"
        release.mkdir(mode=0o700)
        MODULE._protected_directory(release, "release")
        release.chmod(0o720)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(release, "release")

    def test_policy_path_ignores_environment_override(self) -> None:
        previous = os.environ.get("HINDSIGHT_PROVIDER_POLICY_PATH")
        os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = str(
            self.root / "untrusted-policy.json"
        )
        try:
            self.assertEqual(
                MODULE._provider_policy_path(self.root),
                self.root
                / ".config/hindsight-control-plane/provider-runtime-policy.json",
            )
        finally:
            if previous is None:
                os.environ.pop("HINDSIGHT_PROVIDER_POLICY_PATH", None)
            else:
                os.environ["HINDSIGHT_PROVIDER_POLICY_PATH"] = previous

    def test_rejects_writable_or_symlinked_oauth_home_ancestry(self) -> None:
        self.root.chmod(0o750)
        parent = self.root / "provider"
        parent.mkdir(mode=0o755)
        oauth_home = parent / "oauth"
        oauth_home.mkdir(mode=0o700)
        MODULE._protected_directory_ancestry(
            oauth_home,
            self.root,
            "OAuth home",
        )
        MODULE._protected_directory(oauth_home, "OAuth home", private=True)

        oauth_home.chmod(0o750)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(oauth_home, "OAuth home", private=True)
        oauth_home.chmod(0o700)

        parent.chmod(0o770)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory_ancestry(
                oauth_home,
                self.root,
                "OAuth home",
            )
        parent.chmod(0o755)

        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow read,write", oauth_home],
            check=True,
        )
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory(oauth_home, "OAuth home", private=True)
        subprocess.run(["/bin/chmod", "-N", oauth_home], check=True)

        auth = oauth_home / "auth.json"
        auth.write_text("{}")
        auth.chmod(0o600)
        subprocess.run(
            ["/bin/chmod", "+a", "everyone allow read,write", auth],
            check=True,
        )
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._read_protected_file(auth, "OAuth auth")
        subprocess.run(["/bin/chmod", "-N", auth], check=True)

        parent.chmod(0o700)

        link = parent / "oauth-link"
        link.symlink_to(oauth_home, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "not protected"):
            MODULE._protected_directory_ancestry(
                link,
                self.root,
                "OAuth home",
            )


if __name__ == "__main__":
    unittest.main()
