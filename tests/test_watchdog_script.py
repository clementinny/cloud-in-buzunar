import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
MANAGER = PROJECT_DIR / "scripts" / "cloud-services.sh"


class WatchdogScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = MANAGER.read_text(encoding="utf-8")

    def test_watchdog_uses_stable_absolute_script_path(self):
        self.assertIn('SCRIPT_PATH="$SCRIPT_DIR/', self.script)
        self.assertIn('"$SCRIPT_PATH" watchdog', self.script)
        self.assertNotIn('nohup "$0" watchdog', self.script)

    def test_watchdog_exits_after_stop_signal(self):
        self.assertIn("trap 'exit 0' INT TERM", self.script)
        self.assertIn('terminate_child_processes "$process_id"', self.script)
        self.assertIn('wait "$!" || true', self.script)

    def test_watchdog_initializes_database_before_starting(self):
        self.assertIn(
            "from app.database import initialize_database; "
            "initialize_database()",
            self.script,
        )

    def test_watchdog_supports_explicit_lifecycle_and_sample_commands(self):
        for command in (
            "watchdog-start)",
            "watchdog-stop)",
            "watchdog-restart)",
            "watchdog-sample)",
        ):
            with self.subTest(command=command):
                self.assertIn(command, self.script)

    def test_migration_restart_restarts_web_and_watchdog(self):
        migration_case = self.script.split("migration-restart)", 1)[1].split(";;", 1)[0]
        self.assertIn("restart_web", migration_case)
        self.assertIn("start_watchdog", migration_case)

    def test_web_timeout_allows_large_migration_imports(self):
        self.assertIn("--timeout 900", self.script)

    def test_watchdog_interval_is_bounded(self):
        self.assertIn('if [ "$configured" -lt 15 ]', self.script)
        self.assertIn('[ "$configured" -gt 3600 ]', self.script)
        self.assertIn('sleep "$watchdog_interval"', self.script)

    def test_thermal_sample_has_a_timeout_and_success_marker(self):
        self.assertIn(
            'command=(timeout "${THERMAL_CHECK_TIMEOUT_SECONDS:-45}"',
            self.script,
        )
        self.assertIn('> "$WATCHDOG_SAMPLE_FILE"', self.script)

    def test_reliability_alerts_share_the_thermal_snapshot(self):
        self.assertIn(
            '"$PYTHON" -m app.thermal_guardian check',
            self.script,
        )
        self.assertNotIn(
            '"$PYTHON" -m app.reliability_alerts check',
            self.script,
        )
        self.assertNotIn("ALERT_CHECK_INTERVAL_SECONDS", self.script)


if __name__ == "__main__":
    unittest.main()
