import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]


class AiRuntimeAutosleepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.original_home = os.environ.get("HOME")
        cls.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = cls.temporary_directory.name
        os.environ["USERPROFILE"] = cls.temporary_directory.name

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        cls.runtime = importlib.import_module("app.ai_runtime")

    @classmethod
    def tearDownClass(cls):
        if cls.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = cls.original_home
        if cls.original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = cls.original_userprofile
        cls.temporary_directory.cleanup()

    def setUp(self):
        self.runtime.ensure_directories()
        self.runtime.AUTOSTART_CONFIG_FILE.unlink(missing_ok=True)
        self.runtime.ACTIVITY_FILE.unlink(missing_ok=True)

    def write_config(self, value):
        self.runtime.AUTOSTART_CONFIG_FILE.write_text(
            f"AI_IDLE_TIMEOUT_MINUTES={value}\n",
            encoding="utf-8",
        )

    def test_idle_timeout_defaults_and_can_be_disabled(self):
        self.assertEqual(self.runtime.get_idle_timeout_minutes(), 15)
        self.write_config(7)
        self.assertEqual(self.runtime.get_idle_timeout_minutes(), 7)
        self.write_config(0)
        self.assertEqual(self.runtime.get_idle_timeout_minutes(), 0)
        self.write_config("invalid")
        self.assertEqual(self.runtime.get_idle_timeout_minutes(), 15)

    def test_activity_timestamp_round_trip(self):
        self.runtime.mark_ai_activity(1234.5)
        self.assertEqual(
            self.runtime.get_last_activity_timestamp(),
            1234.5,
        )

    def test_idle_model_is_stopped(self):
        self.write_config(15)
        self.runtime.mark_ai_activity(100)

        with (
            patch.object(self.runtime, "get_server_pids", return_value=[42]),
            patch.object(self.runtime, "is_healthy", return_value=True),
            patch.object(self.runtime, "stop_server") as stop_server,
        ):
            result = self.runtime.stop_server_if_idle(now=1001)

        self.assertEqual(result["action"], "stopped")
        stop_server.assert_called_once_with()

    def test_recently_used_model_stays_online(self):
        self.write_config(15)
        self.runtime.mark_ai_activity(900)

        with (
            patch.object(self.runtime, "get_server_pids", return_value=[42]),
            patch.object(self.runtime, "is_healthy", return_value=True),
            patch.object(self.runtime, "stop_server") as stop_server,
        ):
            result = self.runtime.stop_server_if_idle(now=1001)

        self.assertEqual(result["action"], "active")
        stop_server.assert_not_called()

    def test_first_idle_check_initializes_activity(self):
        with (
            patch.object(self.runtime, "get_server_pids", return_value=[42]),
            patch.object(self.runtime, "is_healthy", return_value=True),
            patch.object(self.runtime, "stop_server") as stop_server,
        ):
            result = self.runtime.stop_server_if_idle(now=500)

        self.assertEqual(result["action"], "initialized")
        self.assertEqual(self.runtime.get_last_activity_timestamp(), 500)
        stop_server.assert_not_called()

    def test_watchdog_and_installer_enable_idle_policy(self):
        manager = (PROJECT_DIR / "scripts" / "cloud-services.sh").read_text(
            encoding="utf-8"
        )
        installer = (
            PROJECT_DIR / "scripts" / "install-termux-autostart.sh"
        ).read_text(encoding="utf-8")

        self.assertIn('if [ "$START_AI" != true ]', manager)
        self.assertIn("run_ai_idle_check", manager)
        self.assertIn("AI_IDLE_TIMEOUT_MINUTES=15", installer)


if __name__ == "__main__":
    unittest.main()
