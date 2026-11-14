"""Exercise Baloo's display guard without starting a user service."""

import configparser
import os
from pathlib import Path
import shlex
import subprocess
import unittest


DROP_IN = (
    Path(__file__).resolve().parents[1]
    / "home/dot_config/systemd/user/kde-baloo.service.d/10-display-ready.conf"
)


class BalooStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.unit = configparser.ConfigParser(interpolation=None)
        with DROP_IN.open() as source:
            cls.unit.read_file(source)

    def test_waits_for_kwin_wayland(self):
        self.assertIn(
            "plasma-kwin_wayland.service", self.unit["Unit"]["After"].split()
        )

    def assert_display_guard(self, display_environment, expected_status):
        command = shlex.split(self.unit["Service"]["ExecCondition"])
        self.assertEqual(command[:2], ["/usr/bin/sh", "-c"])
        self.assertEqual(len(command), 3)
        # systemd passes a literal dollar sign for each doubled dollar sign.
        self.assertNotIn("$", command[2].replace("$$", ""))
        command[2] = command[2].replace("$$", "$")
        environment = dict(os.environ)
        environment.pop("WAYLAND_DISPLAY", None)
        environment.pop("DISPLAY", None)
        environment.update(display_environment)
        # The Linux unit path is checked above; use the host POSIX shell on macOS too.
        command[0] = "sh"
        result = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected_status, result.stderr)

    def test_skips_without_a_display(self):
        self.assert_display_guard({}, 1)

    def test_allows_wayland_alone(self):
        self.assert_display_guard({"WAYLAND_DISPLAY": "wayland-0"}, 0)

    def test_allows_x11_alone(self):
        self.assert_display_guard({"DISPLAY": ":0"}, 0)


if __name__ == "__main__":
    unittest.main()
