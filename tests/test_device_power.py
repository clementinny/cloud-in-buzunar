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
                return_value={"voltage": 3946, "temperature": 32.7},
            ),
        ):
            result = device_power.collect_battery_health()

        self.assertEqual(result["voltage_v"], 3.946)
        self.assertEqual(result["temperature_c"], 32.7)

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

    def test_thermal_sensors_are_normalized(self):
        sensors = device_power.parse_thermal_sensors(
            "sensor|battery|35400\nsensor|gpu-therm|61250\ninvalid\n"
        )

        self.assertEqual(sensors[0]["temperature_c"], 35.4)
        self.assertEqual(sensors[1]["temperature_c"], 61.2)

    def test_charge_limit_rejects_unknown_value_before_root_write(self):
        with self.assertRaises(device_power.DevicePowerError):
            device_power.apply_charge_limit("samsung", 73)


if __name__ == "__main__":
    unittest.main()
