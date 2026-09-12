import unittest
from unittest.mock import patch

from app import background_monitor


ROOT_OUTPUT = """
__CLOUD_CPU_FIRST__
cpu  100 0 50 850 0 0 0 0
__CLOUD_CPU_SECOND__
cpu  140 0 70 890 0 0 0 0
__CLOUD_GPU__
busy=25 100
current=400000000
maximum=800000000
__CLOUD_ANDROID_CPU__
  12.5% 222/com.example.camera: 8.0% user + 4.5% kernel
__CLOUD_BATTERY__
capacity=75
temp=335
__CLOUD_THERMAL__
sensor|cpu-0|42000
__CLOUD_THERMAL_SERVICE__
Thermal Status: 0
""".strip()


class BackgroundMonitorTest(unittest.TestCase):
    def test_combined_snapshot_reuses_one_root_session(self):
        resources = {"cpu": {"usage_percent": 50}}
        power = {"battery": {"percentage": 75}, "thermal": {}}

        with (
            patch.object(
                background_monitor,
                "run_root_shell",
                return_value=ROOT_OUTPUT,
            ) as root_shell,
            patch.object(
                background_monitor,
                "collect_resource_usage",
                return_value=resources,
            ) as collect_resources,
            patch.object(
                background_monitor,
                "collect_power_snapshot",
                return_value=power,
            ) as collect_power,
        ):
            result = background_monitor.collect_background_snapshot(
                0.2,
                include_android_processes=True,
            )

        root_shell.assert_called_once()
        resource_arguments = collect_resources.call_args.kwargs
        self.assertFalse(resource_arguments["include_android_processes"])
        self.assertEqual(
            resource_arguments["root_cpu_samples"],
            ((1000, 850), (1100, 890)),
        )
        self.assertEqual(resource_arguments["root_gpu_values"]["busy"], "25 100")
        self.assertEqual(
            resource_arguments["android_cpu_snapshot"]["processes"][0]["pid"],
            222,
        )
        self.assertTrue(collect_power.call_args.kwargs["root_available"])
        self.assertEqual(result, {"resources": resources, "power": power})

    def test_parser_keeps_dumpsys_lines_inside_service_section(self):
        sections = background_monitor.parse_root_monitor_snapshot(ROOT_OUTPUT)

        self.assertEqual(sections["battery"], "capacity=75\ntemp=335")
        self.assertEqual(sections["service"], "Thermal Status: 0")


if __name__ == "__main__":
    unittest.main()
