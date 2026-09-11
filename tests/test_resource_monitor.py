import unittest
from collections import namedtuple
from unittest.mock import patch

from app import resource_monitor


class ResourceMonitorTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
