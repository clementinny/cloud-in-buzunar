import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import service_control


class ServiceControlTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.config_path = (
            Path(self.temporary_directory.name) / "autostart.conf"
        )
        self.config_patch = patch.object(
            service_control,
            "AUTOSTART_CONFIG_FILE",
            self.config_path,
        )
        self.config_patch.start()

    def tearDown(self):
        self.config_patch.stop()
        self.temporary_directory.cleanup()

    def test_setting_is_added_without_losing_existing_values(self):
        self.config_path.write_text(
            "START_WEB=true\nSTART_AI=false\n",
            encoding="utf-8",
        )

        service_control.write_boolean_setting(
            "START_TRANSMISSION",
            False,
        )

        saved_text = self.config_path.read_text(encoding="utf-8")
        self.assertIn("START_WEB=true", saved_text)
        self.assertIn("START_AI=false", saved_text)
        self.assertIn("START_TRANSMISSION=false", saved_text)
        self.assertFalse(service_control.transmission_is_enabled())

    def test_stopping_service_updates_watchdog_and_runs_manager(self):
        with patch.object(
            service_control.subprocess,
            "run",
        ) as run_command:
            enabled = service_control.set_transmission_enabled(False)

        self.assertFalse(enabled)
        self.assertFalse(service_control.transmission_is_enabled())
        command = run_command.call_args.args[0]
        self.assertEqual(command[-1], "transmission-stop")
        self.assertNotIn("shell", run_command.call_args.kwargs)

if __name__ == "__main__":
    unittest.main()
