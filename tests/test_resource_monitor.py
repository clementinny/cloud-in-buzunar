import unittest
from collections import namedtuple
from subprocess import CompletedProcess
from unittest.mock import patch

from app import resource_monitor


class ResourceMonitorTest(unittest.TestCase):
    def test_root_gpu_values_fill_restricted_adreno_metrics(self):
        with (
            patch.object(
                resource_monitor.Path,
                "read_text",
                side_effect=PermissionError,
            ),
            patch.object(
                resource_monitor,
                "read_root_gpu_values",
                return_value={
                    "busy": "25 100",
                    "current": "430000000",
                    "maximum": "845000000",
                },
            ),
        ):
            result = resource_monitor.read_gpu_status()

        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "root")
        self.assertEqual(result["usage_percent"], 25.0)
        self.assertEqual(result["current_frequency_hz"], 430000000)
        self.assertEqual(result["maximum_frequency_hz"], 845000000)

    def test_android_cpuinfo_processes_are_parsed_and_sorted(self):
        output = """
          3.2% 111/system_server: 2.0% user + 1.2% kernel
          18% 222/com.example.camera: 12% user + 6% kernel
          0.4% 333/kworker/0:1: 0% user + 0.4% kernel
        """

        processes = resource_monitor.parse_android_cpuinfo(output)

        self.assertEqual(
            processes,
            [
                {
                    "pid": 222,
                    "name": "com.example.camera",
                    "cpu_percent": 18.0,
                },
                {
                    "pid": 111,
                    "name": "system_server",
                    "cpu_percent": 3.2,
                },
                {
                    "pid": 333,
                    "name": "kworker/0:1",
                    "cpu_percent": 0.4,
                },
            ],
        )

    def test_root_cpu_fallback_is_used_when_android_blocks_proc_stat(self):
        cpu_line = "cpu  100 0 50 800 10 0 0 0\n"

        with (
            patch.object(
                resource_monitor,
                "read_cpu_totals",
                side_effect=PermissionError,
            ),
            patch.object(
                resource_monitor,
                "is_termux_environment",
                return_value=True,
            ),
            patch.object(
                resource_monitor.shutil,
                "which",
                return_value="/system/xbin/su",
            ),
            patch.object(
                resource_monitor.subprocess,
                "run",
                return_value=CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout=cpu_line,
                    stderr="",
                ),
            ),
        ):
            totals, source = resource_monitor.read_cpu_snapshot()

        self.assertEqual(source, "root")
        self.assertEqual(totals, (960, 810))

    def test_process_status_and_stat_are_parsed(self):
        status = resource_monitor.parse_process_status(
            "Name:\tllama-server\nUid:\t10271 10271 10271 10271\n"
            "VmRSS:\t204800 kB\n"
        )
        stat_fields = ["S"] + ["0"] * 19
        stat_fields[11] = "120"
        stat_fields[12] = "30"
        stat_fields[19] = "900"
        statistics = resource_monitor.parse_process_stat(
            "123 (llama server) " + " ".join(stat_fields)
        )

        self.assertEqual(status["uid"], 10271)
        self.assertEqual(status["rss_bytes"], 204800 * 1024)
        self.assertEqual(statistics["cpu_ticks"], 150)
        self.assertEqual(statistics["start_ticks"], 900)

    def test_network_rate_excludes_missing_previous_interface_spike(self):
        result = resource_monitor.build_network_summary(
            {"wlan0": {"received_bytes": 1000, "sent_bytes": 500}},
            {
                "wlan0": {"received_bytes": 1500, "sent_bytes": 700},
                "rmnet0": {"received_bytes": 9000, "sent_bytes": 3000},
            },
            0.5,
        )

        self.assertEqual(result["received_bytes_per_second"], 1000)
        self.assertEqual(result["sent_bytes_per_second"], 400)
        self.assertEqual(len(result["interfaces"]), 2)

    def test_resource_snapshot_calculates_cpu_and_process_usage(self):
        process_before = {
            12: {
                "pid": 12,
                "name": "AI local",
                "service_id": "ai",
                "rss_bytes": 200 * 1024 * 1024,
                "cpu_ticks": 100,
                "start_ticks": 50,
            }
        }
        process_after = {
            12: {
                **process_before[12],
                "cpu_ticks": 125,
            }
        }
        disk_usage = namedtuple("usage", "total used free")(
            1000,
            600,
            400,
        )

        with (
            patch.object(
                resource_monitor,
                "read_meminfo",
                return_value={
                    "MemTotal": 1000 * 1024 * 1024,
                    "MemAvailable": 400 * 1024 * 1024,
                    "SwapTotal": 100 * 1024 * 1024,
                    "SwapFree": 80 * 1024 * 1024,
                },
            ),
            patch.object(
                resource_monitor,
                "read_cpu_totals",
                side_effect=[(1000, 400), (2000, 1000)],
            ),
            patch.object(
                resource_monitor,
                "read_network_totals",
                side_effect=[{}, {}],
            ),
            patch.object(
                resource_monitor,
                "read_processes",
                side_effect=[process_before, process_after],
            ),
            patch.object(
                resource_monitor.time,
                "monotonic",
                side_effect=[10.0, 10.5],
            ),
            patch.object(resource_monitor.time, "sleep"),
            patch.object(
                resource_monitor.shutil,
                "disk_usage",
                return_value=disk_usage,
            ),
            patch.object(
                resource_monitor,
                "read_gpu_status",
                return_value={"available": False},
            ),
            patch.object(
                resource_monitor,
                "ai_is_enabled",
                return_value=False,
            ),
            patch.object(
                resource_monitor,
                "aria2_is_enabled",
                return_value=True,
            ),
            patch.object(
                resource_monitor,
                "transmission_is_enabled",
                return_value=True,
            ),
        ):
            payload = resource_monitor.collect_resource_usage(0.5)

        expected_process_cpu = round(
            25 / resource_monitor.CLOCK_TICKS / 0.5 * 100,
            1,
        )
        self.assertEqual(payload["cpu"]["usage_percent"], 40.0)
        self.assertEqual(payload["memory"]["used_percent"], 60.0)
        self.assertEqual(payload["storage"]["used_percent"], 60.0)
        self.assertEqual(
            payload["processes"][0]["cpu_percent"],
            expected_process_cpu,
        )
        self.assertEqual(payload["processes"][0]["ram_percent"], 20.0)
        self.assertEqual(payload["managed_services"][0]["id"], "ai")
        self.assertEqual(payload["cpu"]["source"], "android")

    def test_resource_snapshot_falls_back_to_termux_cpu_estimate(self):
        process = {
            "pid": 42,
            "name": "Transmission",
            "service_id": "transmission",
            "rss_bytes": 1024,
            "cpu_ticks": 0,
            "start_ticks": 0,
        }
        process_after = {**process, "cpu_ticks": resource_monitor.CLOCK_TICKS}

        with (
            patch.object(
                resource_monitor,
                "read_meminfo",
                return_value={"MemTotal": 1024, "MemAvailable": 512},
            ),
            patch.object(
                resource_monitor,
                "read_cpu_snapshot",
                return_value=(None, None),
            ),
            patch.object(
                resource_monitor,
                "read_network_totals",
                return_value={},
            ),
            patch.object(
                resource_monitor,
                "read_processes",
                side_effect=[{42: process}, {42: process_after}],
            ),
            patch.object(
                resource_monitor.time,
                "monotonic",
                side_effect=[10.0, 11.0],
            ),
            patch.object(resource_monitor.time, "sleep"),
            patch.object(
                resource_monitor.shutil,
                "disk_usage",
                return_value=namedtuple("Usage", "total used free")(
                    100,
                    25,
                    75,
                ),
            ),
            patch.object(
                resource_monitor,
                "read_gpu_status",
                return_value={"available": False},
            ),
            patch.object(
                resource_monitor,
                "get_managed_services",
                return_value=[],
            ),
        ):
            payload = resource_monitor.collect_resource_usage(0.5)

        self.assertEqual(payload["cpu"]["source"], "termux_estimate")
        self.assertAlmostEqual(
            payload["cpu"]["usage_percent"],
            round(100 / resource_monitor.CPU_COUNT, 1),
        )


if __name__ == "__main__":
    unittest.main()
