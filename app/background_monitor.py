from app.device_power import (
    BATTERY_ROOT_COMMAND_BODY,
    THERMAL_ROOT_COMMAND_BODY,
    DevicePowerError,
    collect_power_snapshot,
    run_root_shell,
)
from app.resource_monitor import (
    ROOT_GPU_COMMAND_BODY,
    collect_resource_usage,
    parse_android_cpuinfo,
    parse_cpu_totals,
    parse_root_gpu_output,
)


SECTION_MARKERS = {
    "__CLOUD_CPU_FIRST__": "cpu_first",
    "__CLOUD_CPU_SECOND__": "cpu_second",
    "__CLOUD_GPU__": "gpu",
    "__CLOUD_ANDROID_CPU__": "android_cpu",
    "__CLOUD_BATTERY__": "battery",
    "__CLOUD_THERMAL__": "thermal",
    "__CLOUD_THERMAL_SERVICE__": "service",
}


def build_root_monitor_command(sample_seconds, include_android_processes=False):
    sample_seconds = min(1.0, max(0.05, float(sample_seconds)))
    delay = f"{sample_seconds:.3f}"
    android_command = (
        "dumpsys cpuinfo 2>/dev/null || true"
        if include_android_processes
        else ":"
    )
    return f"""
printf '%s\n' '__CLOUD_CPU_FIRST__'
head -n 1 /proc/stat 2>/dev/null || true
sleep {delay}
printf '%s\n' '__CLOUD_CPU_SECOND__'
head -n 1 /proc/stat 2>/dev/null || true
printf '%s\n' '__CLOUD_GPU__'
{ROOT_GPU_COMMAND_BODY}
printf '%s\n' '__CLOUD_ANDROID_CPU__'
{android_command}
printf '%s\n' '__CLOUD_BATTERY__'
{BATTERY_ROOT_COMMAND_BODY}
printf '%s\n' '__CLOUD_THERMAL__'
{THERMAL_ROOT_COMMAND_BODY}
printf '%s\n' '__CLOUD_THERMAL_SERVICE__'
dumpsys thermalservice 2>/dev/null || true
exit 0
""".strip()


def parse_root_monitor_snapshot(text):
    sections = {name: [] for name in SECTION_MARKERS.values()}
    current = None

    for line in text.splitlines():
        marker = SECTION_MARKERS.get(line.strip())

        if marker is not None:
            current = marker
        elif current is not None:
            sections[current].append(line)

    return {name: "\n".join(lines) for name, lines in sections.items()}


def parse_cpu_section(text):
    try:
        return parse_cpu_totals(text)
    except (ValueError, IndexError):
        return None


def build_power_output(sections):
    return "\n".join(
        (
            "__CLOUD_BATTERY__",
            sections.get("battery", ""),
            "__CLOUD_THERMAL__",
            sections.get("thermal", ""),
            "__CLOUD_THERMAL_SERVICE__",
            sections.get("service", ""),
        )
    )


def build_android_cpu_snapshot(text, requested):
    if not requested:
        return {
            "available": False,
            "processes": [],
            "note": (
                "Lista completă Android este colectată numai la "
                "actualizarea manuală a panoului."
            ),
        }

    processes = parse_android_cpuinfo(text)
    return {
        "available": bool(processes),
        "processes": processes[:50],
        "note": (
            "Raport Android obținut în aceeași sesiune root cu CPU și GPU."
            if processes
            else "Android nu a raportat momentan procese cu activitate CPU."
        ),
    }


def collect_background_snapshot(
    sample_seconds=0.2,
    *,
    include_android_processes=False,
):
    try:
        output = run_root_shell(
            build_root_monitor_command(
                sample_seconds,
                include_android_processes=include_android_processes,
            ),
            timeout=15,
        )
        root_available = True
    except DevicePowerError:
        output = ""
        root_available = False

    sections = parse_root_monitor_snapshot(output)
    cpu_samples = (
        parse_cpu_section(sections["cpu_first"]),
        parse_cpu_section(sections["cpu_second"]),
    )
    resources = collect_resource_usage(
        sample_seconds,
        include_android_processes=False,
        root_cpu_samples=cpu_samples,
        root_gpu_values=parse_root_gpu_output(sections["gpu"]),
        android_cpu_snapshot=build_android_cpu_snapshot(
            sections["android_cpu"],
            include_android_processes,
        ),
    )
    power = collect_power_snapshot(
        root_output=build_power_output(sections),
        root_available=root_available,
    )
    return {"resources": resources, "power": power}
