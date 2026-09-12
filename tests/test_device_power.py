import unittest
from unittest.mock import patch

from app import device_power


class DevicePowerTest(unittest.TestCase):
    def test_battery_health_normalizes_root_metrics(self):
        root_values = """
capacity=68
temp=354
status=Discharging
health=Good
voltage_now=3946000
current_now=-354614
charge_full=3300000
charge_full_design=4500000
cycle_count=321
technology=Li-ion
limit_samsung=85
"""

        with (
            patch.object(device_power, "run_root_shell", return_value=root_values),
            patch.object(device_power, "read_termux_battery_status", return_value={}),
        ):
            result = device_power.collect_battery_health()

        self.assertEqual(result["temperature_c"], 35.4)
        self.assertEqual(result["voltage_v"], 3.946)
        self.assertEqual(result["current_a"], -0.355)
        self.assertEqual(result["power_w"], -1.4)
        self.assertEqual(result["health_percent"], 73.3)
        self.assertEqual(result["cycle_count"], 321)
        self.assertTrue(result["charge_control"]["supported"])
        self.assertEqual(result["charge_control"]["driver"], "samsung")

    def test_termux_voltage_is_interpreted_as_millivolts(self):
        with (
            patch.object(
                device_power,
                "run_root_shell",
                side_effect=device_power.DevicePowerError,
            ),
            patch.object(
                device_power,
                "read_termux_battery_status",
                return_value={
                    "voltage": 3946,
                    "temperature": 32.7,
                    "plugged": "UNPLUGGED",
                },
            ),
        ):
            result = device_power.collect_battery_health()

        self.assertEqual(result["voltage_v"], 3.946)
        self.assertEqual(result["temperature_c"], 32.7)
        self.assertEqual(result["plugged"], "UNPLUGGED")

    def test_battery_health_can_use_energy_capacity_ratio(self):
        root_output = "\n".join(
            (
                "energy_full=3600000",
                "energy_full_design=4000000",
            )
        )

        with (
            patch.object(
                device_power,
                "run_root_shell",
                return_value=root_output,
            ),
            patch.object(
                device_power,
                "read_termux_battery_status",
                return_value={},
            ),
        ):
            result = device_power.collect_battery_health()

        self.assertEqual(result["health_percent"], 90.0)
        self.assertEqual(result["health_estimate_source"], "energy_full")

    def test_complete_root_battery_data_skips_termux_api_process(self):
        root_output = "\n".join(
            (
                "capacity=80",
                "temp=340",
                "voltage_now=4100000",
                "current_now=100000",
                "plugged=PLUGGED_AC",
            )
        )

        with patch.object(
            device_power,
            "read_termux_battery_status",
        ) as termux_status:
            result = device_power.collect_battery_health(
                root_output=root_output,
                root_available=True,
            )

        termux_status.assert_not_called()
        self.assertEqual(result["plugged"], "PLUGGED_AC")

    def test_thermal_sensors_are_normalized(self):
        sensors = device_power.parse_thermal_sensors(
            "sensor|battery|35400\nsensor|gpu-therm|61250\ninvalid\n"
        )

        self.assertEqual(sensors[0]["temperature_c"], 35.4)
        self.assertEqual(sensors[1]["temperature_c"], 61.2)

    def test_charge_limit_rejects_unknown_value_before_root_write(self):
        with self.assertRaises(device_power.DevicePowerError):
            device_power.apply_charge_limit("samsung", 73)

    def test_power_snapshot_uses_one_root_session(self):
        root_output = """
__CLOUD_BATTERY__
capacity=70
temp=330
status=Charging
__CLOUD_THERMAL__
sensor|cpuss-0-usr|42000
sensor|gpu-therm|39000
__CLOUD_THERMAL_SERVICE__
Thermal Status: 0
"""

        with (
            patch.object(
                device_power,
                "run_root_shell",
                return_value=root_output,
            ) as root_call,
            patch.object(
                device_power,
                "read_termux_battery_status",
                return_value={},
            ),
        ):
            result = device_power.collect_power_snapshot()

        root_call.assert_called_once()
        self.assertEqual(result["battery"]["percentage"], 70)
        self.assertEqual(result["thermal"]["cpu_temperature_c"], 42.0)
        self.assertEqual(result["thermal"]["gpu_temperature_c"], 39.0)
        self.assertEqual(result["thermal"]["severity"], 0)


if __name__ == "__main__":
    unittest.main()
