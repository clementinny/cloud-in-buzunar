import unittest
from unittest.mock import patch

from app import thermal_guardian


class ThermalGuardianTest(unittest.TestCase):
    def test_temperature_levels_use_battery_hysteresis_thresholds(self):
        policy = {**thermal_guardian.DEFAULT_POLICY}

        self.assertEqual(
            thermal_guardian.determine_thermal_level(
                policy,
                {"battery": {"temperature_c": 39}, "thermal": {}},
            ),
            "normal",
        )
        self.assertEqual(
            thermal_guardian.determine_thermal_level(
                policy,
                {"battery": {"temperature_c": 41}, "thermal": {}},
            ),
            "warning",
        )
        self.assertEqual(
            thermal_guardian.determine_thermal_level(
                policy,
                {"battery": {"temperature_c": 44}, "thermal": {}},
            ),
            "critical",
        )

    def test_policy_requires_ordered_thresholds(self):
        with self.assertRaises(thermal_guardian.ThermalPolicyError):
            thermal_guardian.validate_thermal_policy(
                {
                    "recovery_temperature_c": 42,
                    "warning_temperature_c": 40,
                    "critical_temperature_c": 43,
                }
            )

    def test_missing_thermal_data_does_not_count_as_recovered(self):
        policy = {**thermal_guardian.DEFAULT_POLICY}
        power = {"battery": {}, "thermal": {}}

        self.assertEqual(
            thermal_guardian.determine_thermal_level(policy, power),
            "unknown",
        )
        self.assertFalse(
            thermal_guardian.temperatures_are_recovered(policy, power)
        )

    def test_warning_stops_only_running_selected_services(self):
        resources = {
            "cpu": {"usage_percent": 20},
            "gpu": {"usage_percent": 5},
            "managed_services": [
                {"id": "ai", "running": True},
                {"id": "transmission", "running": False},
                {"id": "aria2", "running": True},
            ],
        }
        power = {
            "battery": {
                "temperature_c": 41,
                "percentage": 60,
                "charge_control": {"supported": False},
            },
            "thermal": {},
        }

        with (
            patch.object(thermal_guardian, "get_thermal_policy", return_value={**thermal_guardian.DEFAULT_POLICY}),
            patch.object(thermal_guardian, "collect_resource_usage", return_value=resources),
            patch.object(thermal_guardian, "collect_power_snapshot", return_value=power),
            patch.object(thermal_guardian, "record_system_metric"),
            patch.object(thermal_guardian, "prune_system_metrics"),
            patch.object(thermal_guardian, "suspend_service", return_value=True) as suspend,
            patch.object(thermal_guardian, "atomic_write_json"),
        ):
            result = thermal_guardian.run_guardian_check()

        self.assertEqual(result["level"], "warning")
        suspend.assert_called_once_with("ai")


if __name__ == "__main__":
    unittest.main()
