"""Self-checks for the parts of taxis that change or recover a TV."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import taxis as tx
import taxis_gui as gui


class ParseChoice(unittest.TestCase):
    """parse_choice turns '1,3,5-7' style input into 0-based indexes."""

    def test_ranges_and_lists(self):
        self.assertEqual(tx.parse_choice("all", 4), [0, 1, 2, 3])
        self.assertEqual(tx.parse_choice("1,3", 5), [0, 2])
        self.assertEqual(tx.parse_choice("2-4", 6), [1, 2, 3])
        self.assertEqual(tx.parse_choice("none", 4), [])
        self.assertEqual(tx.parse_choice("0", 4), [])

    def test_bad_input_returns_none(self):
        for bad in ("x", "9", "3-1", "1,,2", "-"):
            self.assertIsNone(tx.parse_choice(bad, 4), bad)


class PackageGuard(unittest.TestCase):
    """valid_pkg/valid_comp must reject anything that could inject shell commands."""

    def test_accepts_real_names(self):
        self.assertTrue(tx.valid_pkg("com.amazon.shoptv.client"))
        self.assertTrue(tx.valid_pkg("android"))
        self.assertTrue(tx.valid_comp("com.taxis.launcher/.MainActivity"))
        self.assertTrue(tx.valid_comp("com.foo/com.foo.Activity$Inner"))

    def test_rejects_injection(self):
        for bad in ("com.x; reboot", "com.x && rm -rf /", "com.x$(id)", "a b", "", None):
            self.assertFalse(tx.valid_pkg(bad), bad)


class ProfileMerge(unittest.TestCase):
    """Each tier must include the ones before it, and never.txt must always win."""

    def test_tiers_grow(self):
        tx.SET = "firetv"
        safe = set(tx.plan_for("safe"))
        medium = set(tx.plan_for("medium"))
        aggressive = set(tx.plan_for("aggressive"))
        self.assertTrue(safe <= medium <= aggressive)

    def test_never_excluded(self):
        tx.SET = "firetv"
        plan = tx.plan_for("aggressive")
        for pkg in tx.never():
            self.assertNotIn(pkg, plan)


class TvFolder(unittest.TestCase):
    """TV storage paths must never mix the recovery history of different TVs."""

    def test_hardware_serial_is_the_stable_identity(self):
        """Use the TV serial even when its network address changes."""
        with patch.object(gui, "TV_DIR", Path("tvs")):
            folder = gui.tv_dir_for("Living Room TV", "ABC123", "192.168.1.50")
        self.assertEqual(folder, Path("tvs") / "Living_Room_TV_ABC123")

    def test_ip_is_used_when_the_tv_has_no_serial(self):
        """Use the current IP only when Android reports no hardware serial."""
        with patch.object(gui, "TV_DIR", Path("tvs")):
            folder = gui.tv_dir_for("Smart TV", "unknown", "192.168.1.50")
        self.assertEqual(folder, Path("tvs") / "Smart_TV_192.168.1.50")


class SessionRecovery(unittest.TestCase):
    """Recovery must stay with one TV and reject unsafe recorded command values."""

    # Returns stable fake ADB answers while recording every recovery command.
    def fake_shell(self, serial, command, timeout=30):
        self.shell_commands.append(command)
        if command == "getprop ro.product.model":
            return "Target TV"
        if command == "getprop ro.serialno":
            return "SER-A"
        return "Package enabled"

    def test_revert_ignores_unsafe_recorded_values(self):
        """Undo must never pass injected package or component text to the TV shell."""
        with TemporaryDirectory() as temp_dir:
            engine = gui.Engine()
            engine.serial = "192.168.1.50:5555"
            engine.dir = Path(temp_dir)
            session_dir = engine.dir / "sessions" / "one"
            session_dir.mkdir(parents=True)
            session = {
                "id": "one",
                "actions": {
                    "hidden_packages": ["com.safe.home", "com.bad;reboot"],
                    "hidden_components": ["com.safe.home/.MainActivity", "com.bad/.MainActivity;reboot"],
                    "disabled": ["com.safe.app", "com.bad && reboot"],
                },
                "reverted": False,
            }
            (session_dir / "session.json").write_text(json.dumps(session))
            with patch.object(gui.tx, "shell", return_value="Package enabled") as shell_mock:
                engine.revert("one", Mock())
        commands = [call.args[1] for call in shell_mock.call_args_list]
        self.assertIn("pm enable com.safe.home", commands)
        self.assertIn("pm enable com.safe.home/.MainActivity", commands)
        self.assertIn("pm enable com.safe.app", commands)
        self.assertFalse(any("bad" in command or "reboot" in command for command in commands))

    def test_emergency_restore_reads_only_the_connected_tv(self):
        """Rescue must not apply sessions saved for another TV."""
        with TemporaryDirectory() as temp_dir, patch.object(gui, "TV_DIR", Path(temp_dir)):
            target_dir = gui.tv_dir_for("Target TV", "SER-A", "192.168.1.50") / "sessions" / "target"
            other_dir = gui.tv_dir_for("Other TV", "SER-B", "192.168.1.60") / "sessions" / "other"
            target_dir.mkdir(parents=True)
            other_dir.mkdir(parents=True)
            target_session = {"before": {"home": "com.target.home/.MainActivity"},
                              "actions": {"hidden_packages": ["com.target.home"]}}
            other_session = {"before": {"home": "com.other.home/.MainActivity"},
                             "actions": {"hidden_packages": ["com.other.home"]}}
            (target_dir / "session.json").write_text(json.dumps(target_session))
            (other_dir / "session.json").write_text(json.dumps(other_session))
            engine = gui.Engine()
            self.shell_commands = []
            installed = {"com.target.home", "com.other.home"}
            with patch.object(gui.tx, "need_adb"), \
                    patch.object(gui.tx, "sh", return_value=(0, "connected")), \
                    patch.object(gui.tx, "shell", side_effect=self.fake_shell), \
                    patch.object(gui.tx, "pkg_sets", return_value=(installed, set())), \
                    patch.object(engine, "_state", return_value="device"), \
                    patch.object(engine, "_set_home_redirect", return_value=False), \
                    patch.object(gui.time, "sleep"):
                engine.emergency_restore("192.168.1.50", "5555", Mock(), tries=1, wait=0)
        self.assertIn("pm enable com.target.home", self.shell_commands)
        self.assertIn("cmd package set-home-activity --user 0 com.target.home/.MainActivity", self.shell_commands)
        self.assertFalse(any("com.other.home" in command for command in self.shell_commands))


if __name__ == "__main__":
    unittest.main()
