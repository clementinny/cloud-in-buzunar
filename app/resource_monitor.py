import os
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from app.service_control import (
    ai_is_enabled,
    aria2_is_enabled,
    transmission_is_enabled,
)


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
PROC_ROOT = Path("/proc")
CPU_COUNT = max(1, os.cpu_count() or 1)
ROOT_COMMAND_TIMEOUT_SECONDS = 2
ANDROID_CPUINFO_TIMEOUT_SECONDS = 5
ANDROID_CPU_PROCESS_PATTERN = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)%\s+(\d+)/(.+?):\s+"
    r"[0-9]+(?:\.[0-9]+)?%\s+(?:user|usr)\b"
)
ROOT_GPU_COMMAND = (
    "value=$(cat /sys/class/kgsl/kgsl-3d0/gpubusy 2>/dev/null); "
    "[ -n \"$value\" ] && printf 'busy=%s\\n' \"$value\"; "
    "value=$(cat /sys/class/kgsl/kgsl-3d0/gpuclk 2>/dev/null); "
    "[ -n \"$value\" ] && printf 'current=%s\\n' \"$value\"; "
    "value=$(cat /sys/class/kgsl/kgsl-3d0/devfreq/cur_freq 2>/dev/null); "
    "[ -n \"$value\" ] && printf 'current_devfreq=%s\\n' \"$value\"; "
    "value=$(cat /sys/class/kgsl/kgsl-3d0/max_gpuclk 2>/dev/null); "
    "[ -n \"$value\" ] && printf 'maximum=%s\\n' \"$value\"; "
    "value=$(cat /sys/class/kgsl/kgsl-3d0/devfreq/max_freq 2>/dev/null); "
    "[ -n \"$value\" ] && printf 'maximum_devfreq=%s\\n' \"$value\"; "
    "exit 0"
)

try:
    CLOCK_TICKS = int(os.sysconf("SC_CLK_TCK"))
except (AttributeError, OSError, TypeError, ValueError):
    CLOCK_TICKS = 100


def read_meminfo(proc_root=PROC_ROOT):
    values = {}

    for line in (proc_root / "meminfo").read_text(
        encoding="utf-8"
    ).splitlines():
        name, raw_value = line.split(":", 1)
        values[name] = int(raw_value.strip().split()[0]) * 1024

    return values


def parse_cpu_totals(text):
    first_line = text.splitlines()[0]
    fields = first_line.split()

    if not fields or fields[0] != "cpu":
        raise ValueError("Invalid CPU statistics")

    values = [int(value) for value in fields[1:9]]
    values += [0] * (8 - len(values))
    user, nice, system, idle, io_wait, irq, soft_irq, steal = values[:8]
    idle_ticks = idle + io_wait
    total_ticks = (
        user + nice + system + idle + io_wait + irq + soft_irq + steal
    )

    return total_ticks, idle_ticks


def read_cpu_totals(proc_root=PROC_ROOT):
    return parse_cpu_totals(
        (proc_root / "stat").read_text(encoding="utf-8")
    )


def is_termux_environment():
    prefix = os.environ.get("PREFIX", "")
    return "com.termux" in prefix or Path(
        "/data/data/com.termux"
    ).exists()


def read_root_cpu_totals():
    if not is_termux_environment():
        raise OSError("Root CPU fallback is only used in Termux")

    su_command = shutil.which("su")

    if not su_command:
        raise OSError("su is not available")

    result = subprocess.run(
        [su_command, "-c", "cat /proc/stat"],
        capture_output=True,
        check=False,
        text=True,
        timeout=ROOT_COMMAND_TIMEOUT_SECONDS,
    )

    if result.returncode != 0 or not result.stdout.strip():
        raise OSError("Root access to CPU statistics failed")

    return parse_cpu_totals(result.stdout)


def read_cpu_snapshot():
    try:
        return read_cpu_totals(), "android"
    except (OSError, ValueError, IndexError):
        pass

    try:
        return read_root_cpu_totals(), "root"
    except (
        OSError,
        ValueError,
        IndexError,
        subprocess.SubprocessError,
    ):
        return None, None


def parse_android_cpuinfo(text):
    processes = []

    for line in text.splitlines():
        match = ANDROID_CPU_PROCESS_PATTERN.match(line)

        if not match:
            continue

        cpu_percent, pid, name = match.groups()
        processes.append(
            {
                "pid": int(pid),
                "name": name.strip(),
                "cpu_percent": float(cpu_percent),
            }
        )

    processes.sort(
        key=lambda process: process["cpu_percent"],
        reverse=True,
    )
    return processes


def read_android_cpu_processes():
    unavailable = {
        "available": False,
        "processes": [],
        "note": (
            "Acordă aplicației Termux acces root pentru a vedea "
            "procesele întregului telefon."
        ),
    }

    if not is_termux_environment():
        return unavailable

    su_command = shutil.which("su")

    if not su_command:
        return unavailable

    try:
        result = subprocess.run(
            [su_command, "-c", "dumpsys cpuinfo"],
            capture_output=True,
            check=False,
            text=True,
            timeout=ANDROID_CPUINFO_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return unavailable

    if result.returncode != 0:
        return unavailable

    processes = parse_android_cpuinfo(result.stdout)

    if not processes:
        return {
            **unavailable,
            "note": "Android nu a raportat momentan procese cu activitate CPU.",
        }

    return {
        "available": True,
        "processes": processes[:50],
        "note": (
            "Raport Android obținut cu root; include aplicațiile, "
            "serviciile de sistem și procesele Termux."
        ),
    }


def read_network_totals(proc_root=PROC_ROOT):
    interfaces = {}

    for line in (proc_root / "net" / "dev").read_text(
        encoding="utf-8"
    ).splitlines()[2:]:
        if ":" not in line:
            continue

        interface, raw_values = line.split(":", 1)
        interface = interface.strip()
        values = raw_values.split()

        if interface == "lo" or len(values) < 16:
            continue

        interfaces[interface] = {
            "received_bytes": int(values[0]),
            "sent_bytes": int(values[8]),
        }

    return interfaces


def parse_process_status(text):
    values = {}

    for line in text.splitlines():
        if ":" not in line:
            continue

        name, raw_value = line.split(":", 1)
        values[name] = raw_value.strip()

    uid = int(values["Uid"].split()[0])
    rss_fields = values.get("VmRSS", "0 kB").split()
    rss_bytes = int(rss_fields[0]) * 1024

    return {
        "name": values.get("Name", "necunoscut"),
        "uid": uid,
        "rss_bytes": rss_bytes,
    }


def parse_process_stat(text):
    closing_parenthesis = text.rfind(")")

    if closing_parenthesis < 0:
        raise ValueError("Invalid process statistics")

    fields = text[closing_parenthesis + 2:].split()

    if len(fields) < 20:
        raise ValueError("Incomplete process statistics")

    return {
        "cpu_ticks": int(fields[11]) + int(fields[12]),
        "start_ticks": int(fields[19]),
    }


def identify_process(name, command):
    normalized = command.lower()
    normalized_name = name.lower()

    if "llama-server" in normalized or normalized_name == "llama-server":
        return "AI local", "ai"

    if (
        "transmission-daemon" in normalized
        or normalized_name == "transmission-daemon"
    ):
        return "Transmission", "transmission"

    if "aria2c" in normalized or normalized_name == "aria2c":
        return "aria2", "aria2"

    if "gunicorn" in normalized and "app.main:app" in normalized:
        return "Server web (Gunicorn)", "web"

    if "cloud-services.sh" in normalized and "watchdog" in normalized:
        return "Watchdog CloudInBuzunar", "watchdog"

    if normalized_name == "sshd" or "/sshd" in normalized:
        return "Acces SSH", "ssh"

    if "ffmpeg" in normalized or normalized_name == "ffmpeg":
        return "Analiză audio/video (FFmpeg)", "ffmpeg"

    if normalized_name.startswith("python"):
        return "Proces Python", "python"

    return name, "other"


def read_process(pid, expected_uid, proc_root=PROC_ROOT):
    process_root = proc_root / str(pid)
    status = parse_process_status(
        (process_root / "status").read_text(
            encoding="utf-8",
            errors="replace",
        )
    )

    if expected_uid is not None and status["uid"] != expected_uid:
        return None

    statistics = parse_process_stat(
        (process_root / "stat").read_text(
            encoding="utf-8",
            errors="replace",
        )
    )
    command = (process_root / "cmdline").read_bytes().replace(
        b"\0",
        b" ",
    ).decode("utf-8", errors="replace")
    display_name, service_id = identify_process(status["name"], command)

    return {
        "pid": int(pid),
        "name": display_name,
        "service_id": service_id,
        "rss_bytes": status["rss_bytes"],
        **statistics,
    }


def read_processes(proc_root=PROC_ROOT):
    processes = {}
    expected_uid = getattr(os, "getuid", lambda: None)()

    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes

    for entry in entries:
        if not entry.name.isdigit():
            continue

        try:
            process = read_process(entry.name, expected_uid, proc_root)
        except (OSError, ValueError, KeyError, IndexError):
            continue

        if process is not None:
            processes[process["pid"]] = process

    return processes


def calculate_percent(value, total):
    return value / total * 100 if total > 0 else 0.0


def parse_root_gpu_output(text):
    values = {}

    for line in text.splitlines():
        if "=" not in line:
            continue

        name, raw_value = line.split("=", 1)
        values[name.strip()] = raw_value.strip()

    return values


def read_root_gpu_values():
    if not is_termux_environment():
        return {}

    su_command = shutil.which("su")

    if not su_command:
        return {}

    try:
        result = subprocess.run(
            [su_command, "-c", ROOT_GPU_COMMAND],
            capture_output=True,
            check=False,
            text=True,
            timeout=ROOT_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    if result.returncode != 0:
        return {}

    return parse_root_gpu_output(result.stdout)


def read_gpu_status():
    gpu_busy_path = Path("/sys/class/kgsl/kgsl-3d0/gpubusy")
    current_frequency_paths = [
        Path("/sys/class/kgsl/kgsl-3d0/gpuclk"),
        Path("/sys/class/kgsl/kgsl-3d0/devfreq/cur_freq"),
    ]
    maximum_frequency_paths = [
        Path("/sys/class/kgsl/kgsl-3d0/max_gpuclk"),
        Path("/sys/class/kgsl/kgsl-3d0/devfreq/max_freq"),
    ]
    result = {
        "available": False,
        "usage_percent": None,
        "current_frequency_hz": None,
        "maximum_frequency_hz": None,
        "source": None,
        "note": (
            "Android nu expune statisticile GPU acestui proces Termux."
        ),
    }

    try:
        busy, total = [
            int(value)
            for value in gpu_busy_path.read_text(
                encoding="utf-8"
            ).split()[:2]
        ]
        result["usage_percent"] = min(
            100.0,
            max(0.0, calculate_percent(busy, total)),
        )
        result["available"] = True
        result["source"] = "android"
        result["note"] = "Utilizare GPU raportată de driverul Android."
    except (OSError, ValueError, IndexError):
        pass

    for path in current_frequency_paths:
        try:
            result["current_frequency_hz"] = int(
                path.read_text(encoding="utf-8").strip()
            )
            result["available"] = True
            result["source"] = "android"
            break
        except (OSError, ValueError):
            continue

    for path in maximum_frequency_paths:
        try:
            result["maximum_frequency_hz"] = int(
                path.read_text(encoding="utf-8").strip()
            )
            result["available"] = True
            result["source"] = "android"
            break
        except (OSError, ValueError):
            continue

    if (
        result["usage_percent"] is None
        or result["current_frequency_hz"] is None
        or result["maximum_frequency_hz"] is None
    ):
        root_values = read_root_gpu_values()
        root_used = False

        if result["usage_percent"] is None and "busy" in root_values:
            try:
                busy, total = [
                    int(value) for value in root_values["busy"].split()[:2]
                ]
                result["usage_percent"] = min(
                    100.0,
                    max(0.0, calculate_percent(busy, total)),
                )
                root_used = True
            except (ValueError, IndexError):
                pass

        if result["current_frequency_hz"] is None:
            for name in ("current", "current_devfreq"):
                try:
                    result["current_frequency_hz"] = int(root_values[name])
                    root_used = True
                    break
                except (KeyError, ValueError):
                    continue

        if result["maximum_frequency_hz"] is None:
            for name in ("maximum", "maximum_devfreq"):
                try:
                    result["maximum_frequency_hz"] = int(root_values[name])
                    root_used = True
                    break
                except (KeyError, ValueError):
                    continue

        if root_used:
            result["available"] = True
            result["source"] = "root"
            result["note"] = (
                "Utilizare și frecvență GPU citite din driverul Adreno "
                "cu permisiune root."
            )

    return result


def build_network_summary(first, second, elapsed_seconds):
    interface_names = sorted(set(first) | set(second))
    interfaces = []

    for name in interface_names:
        before = first.get(name, {})
        after = second.get(name, {})
        received_total = int(after.get("received_bytes", 0))
        sent_total = int(after.get("sent_bytes", 0))
        received_delta = max(
            0,
            received_total - int(before.get("received_bytes", received_total)),
        )
        sent_delta = max(
            0,
            sent_total - int(before.get("sent_bytes", sent_total)),
        )
        interfaces.append(
            {
                "name": name,
                "received_bytes_per_second": received_delta / elapsed_seconds,
                "sent_bytes_per_second": sent_delta / elapsed_seconds,
                "received_bytes": received_total,
                "sent_bytes": sent_total,
            }
        )

    return {
        "received_bytes_per_second": sum(
            item["received_bytes_per_second"] for item in interfaces
        ),
        "sent_bytes_per_second": sum(
            item["sent_bytes_per_second"] for item in interfaces
        ),
        "received_bytes": sum(item["received_bytes"] for item in interfaces),
        "sent_bytes": sum(item["sent_bytes"] for item in interfaces),
        "interfaces": interfaces,
        "note": "Include traficul LAN și internet; loopback-ul este exclus.",
    }


def get_managed_services(processes):
    running_services = {
        process["service_id"] for process in processes
    }

    return [
        {
            "id": "ai",
            "name": "AI local",
            "enabled": ai_is_enabled(),
            "running": "ai" in running_services,
            "impact": "Oprirea eliberează cel mai mult RAM și CPU.",
        },
        {
            "id": "transmission",
            "name": "Transmission",
            "enabled": transmission_is_enabled(),
            "running": "transmission" in running_services,
            "impact": "Oprirea întrerupe descărcarea și seeding-ul.",
        },
        {
            "id": "aria2",
            "name": "aria2",
            "enabled": aria2_is_enabled(),
            "running": "aria2" in running_services,
            "impact": "Oprirea întrerupe descărcările aria2 active.",
        },
    ]


def collect_resource_usage(sample_seconds=0.3):
    sample_seconds = min(1.0, max(0.05, float(sample_seconds)))

    try:
        memory = read_meminfo()
    except (OSError, ValueError, KeyError, IndexError):
        memory = {}

    first_cpu, first_cpu_source = read_cpu_snapshot()

    try:
        first_network = read_network_totals()
    except (OSError, ValueError, IndexError):
        first_network = {}

    first_processes = read_processes()
    started_at = time.monotonic()
    time.sleep(sample_seconds)
    elapsed_seconds = max(0.001, time.monotonic() - started_at)
    second_processes = read_processes()

    second_cpu, second_cpu_source = read_cpu_snapshot()

    try:
        second_network = read_network_totals()
    except (OSError, ValueError, IndexError):
        second_network = {}

    total_memory = int(memory.get("MemTotal", 0))
    available_memory = int(memory.get("MemAvailable", 0))
    used_memory = max(0, total_memory - available_memory)
    system_uptime = 0.0

    try:
        system_uptime = float(
            (PROC_ROOT / "uptime").read_text(
                encoding="utf-8"
            ).split()[0]
        )
    except (OSError, ValueError, IndexError):
        pass

    processes = []

    for pid, process in second_processes.items():
        previous = first_processes.get(pid)
        tick_delta = 0

        if previous is not None:
            tick_delta = max(
                0,
                process["cpu_ticks"] - previous["cpu_ticks"],
            )

        cpu_percent = (
            tick_delta / CLOCK_TICKS / elapsed_seconds * 100
        )
        uptime_seconds = max(
            0,
            system_uptime - process["start_ticks"] / CLOCK_TICKS,
        )
        processes.append(
            {
                "pid": pid,
                "name": process["name"],
                "service_id": process["service_id"],
                "cpu_percent": round(cpu_percent, 1),
                "device_cpu_percent": round(cpu_percent / CPU_COUNT, 1),
                "ram_percent": round(
                    calculate_percent(process["rss_bytes"], total_memory),
                    2,
                ),
                "rss_bytes": process["rss_bytes"],
                "uptime_seconds": round(uptime_seconds),
            }
        )

    processes.sort(
        key=lambda process: (
            process["cpu_percent"],
            process["rss_bytes"],
        ),
        reverse=True,
    )

    cpu_percent = None
    cpu_source = None

    if (
        first_cpu is not None
        and second_cpu is not None
        and first_cpu_source == second_cpu_source
    ):
        total_delta = max(0, second_cpu[0] - first_cpu[0])
        idle_delta = max(0, second_cpu[1] - first_cpu[1])
        cpu_percent = calculate_percent(total_delta - idle_delta, total_delta)
        cpu_source = second_cpu_source

    visible_process_cpu_percent = min(
        100.0,
        sum(process["cpu_percent"] for process in processes) / CPU_COUNT,
    )

    if cpu_percent is None and processes:
        cpu_percent = visible_process_cpu_percent
        cpu_source = "termux_estimate"

    try:
        storage = shutil.disk_usage(DATA_DIR)
        storage_used = storage.total - storage.free
        storage_summary = {
            "available": True,
            "total_bytes": storage.total,
            "used_bytes": storage_used,
            "free_bytes": storage.free,
            "used_percent": round(
                calculate_percent(storage_used, storage.total),
                1,
            ),
        }
    except OSError:
        storage_summary = {"available": False}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_milliseconds": round(elapsed_seconds * 1000),
        "cpu": {
            "available": cpu_percent is not None,
            "usage_percent": (
                round(cpu_percent, 1) if cpu_percent is not None else None
            ),
            "logical_cores": CPU_COUNT,
            "source": cpu_source,
            "visible_process_usage_percent": round(
                visible_process_cpu_percent,
                1,
            ),
            "note": {
                "android": "Utilizare totală raportată direct de Android.",
                "root": "Utilizare totală citită cu permisiune root.",
                "termux_estimate": (
                    "Estimare din procesele vizibile în Termux; "
                    "procesele Android din alte aplicații nu sunt incluse."
                ),
            }.get(cpu_source, "Utilizarea CPU nu poate fi citită."),
        },
        "memory": {
            "available": total_memory > 0,
            "total_bytes": total_memory,
            "used_bytes": used_memory,
            "available_bytes": available_memory,
            "used_percent": round(
                calculate_percent(used_memory, total_memory),
                1,
            ),
            "swap_used_bytes": max(
                0,
                int(memory.get("SwapTotal", 0))
                - int(memory.get("SwapFree", 0)),
            ),
        },
        "storage": storage_summary,
        "network": build_network_summary(
            first_network,
            second_network,
            elapsed_seconds,
        ),
        "gpu": read_gpu_status(),
        "android_cpu": read_android_cpu_processes(),
        "processes": processes[:50],
        "managed_services": get_managed_services(processes),
        "process_note": (
            "Sunt afișate procesele vizibile utilizatorului Termux. "
            "CPU proces folosește convenția top: un nucleu ocupat = 100%."
        ),
    }
