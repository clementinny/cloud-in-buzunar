import json
import os
import re
import shutil
import subprocess
from pathlib import Path


ROOT_TIMEOUT_SECONDS = 6
BATTERY_ROOT_COMMAND = """
base=/sys/class/power_supply/battery
for name in capacity temp status health voltage_now current_now current_avg \
charge_counter charge_full charge_full_design energy_full \
energy_full_design cycle_count technology; do
    path="$base/$name"
    if [ -r "$path" ]; then
        value=$(cat "$path" 2>/dev/null)
        [ -n "$value" ] && printf '%s=%s\n' "$name" "$value"
    fi
done
for item in \
    "standard:$base/charge_control_end_threshold" \
    "samsung:$base/batt_full_capacity"; do
    driver=${item%%:*}
    path=${item#*:}
    if [ -r "$path" ]; then
        value=$(cat "$path" 2>/dev/null)
        [ -n "$value" ] && printf 'limit_%s=%s\n' "$driver" "$value"
    fi
done
exit 0
""".strip()
THERMAL_ROOT_COMMAND = """
for zone in /sys/class/thermal/thermal_zone*; do
    [ -d "$zone" ] || continue
    type=$(cat "$zone/type" 2>/dev/null)
    temp=$(cat "$zone/temp" 2>/dev/null)
    [ -n "$type" ] && [ -n "$temp" ] \
        && printf 'sensor|%s|%s\n' "$type" "$temp"
done
exit 0
""".strip()
CHARGE_LIMIT_PATHS = {
    "standard": "/sys/class/power_supply/battery/charge_control_end_threshold",
    "samsung": "/sys/class/power_supply/battery/batt_full_capacity",
}
ALLOWED_CHARGE_LIMITS = {80, 85, 100}
THERMAL_STATUS_LABELS = {
    0: "Fără limitare",
    1: "Limitare ușoară",
    2: "Limitare moderată",
    3: "Limitare severă",
    4: "Limitare critică",
    5: "Urgență termică",
    6: "Oprire termică",
}


class DevicePowerError(RuntimeError):
    pass


def is_termux_environment():
    return "com.termux" in os.environ.get("PREFIX", "") or Path(
        "/data/data/com.termux"
    ).exists()


def run_root_shell(command, timeout=ROOT_TIMEOUT_SECONDS):
    if not is_termux_environment():
        raise DevicePowerError("Comanda root este disponibilă numai în Termux.")

    su_command = shutil.which("su")

    if not su_command:
        raise DevicePowerError("Comanda su nu este disponibilă.")

    try:
        result = subprocess.run(
            [su_command, "-c", command],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise DevicePowerError("Comanda root nu a putut fi executată.") from error

    if result.returncode != 0:
        raise DevicePowerError("Accesul root a fost refuzat sau a eșuat.")

    return result.stdout


def parse_key_values(text):
    values = {}

    for line in text.splitlines():
        if "=" not in line:
            continue

        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()

    return values


def number(values, name):
    try:
        return float(values[name])
    except (KeyError, TypeError, ValueError):
        return None


def normalize_temperature(value):
    if value is None:
        return None

    value = float(value)

    if abs(value) > 1000:
        value /= 1000
    elif abs(value) > 100:
        value /= 10

    return round(value, 1)


def normalize_voltage(value):
    if value is None:
        return None

    value = float(value)
    return round(value / 1_000_000 if abs(value) > 10_000 else value, 3)


def normalize_termux_voltage(value):
    if value is None:
        return None

    value = float(value)
    return round(value / 1000 if abs(value) > 100 else value, 3)


def normalize_current(value):
    if value is None:
        return None

    value = float(value)
    return round(value / 1_000_000 if abs(value) > 10_000 else value, 3)


def normalize_capacity_ah(value):
    if value is None:
        return None

    value = float(value)
    return round(value / 1_000_000 if abs(value) > 10_000 else value, 3)


def read_termux_battery_status():
    command = shutil.which("termux-battery-status")

    if not command:
        return {}

    try:
        result = subprocess.run(
            [command],
            capture_output=True,
            check=False,
            text=True,
            timeout=4,
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}

    return payload if result.returncode == 0 and isinstance(payload, dict) else {}


def collect_battery_health():
    try:
        values = parse_key_values(run_root_shell(BATTERY_ROOT_COMMAND))
        root_available = True
    except DevicePowerError:
        values = {}
        root_available = False

    termux = read_termux_battery_status()
    percentage = number(values, "capacity")
    temperature = normalize_temperature(number(values, "temp"))
    voltage = normalize_voltage(number(values, "voltage_now"))
    current = normalize_current(
        number(values, "current_now") or number(values, "current_avg")
    )
    raw_full_charge = number(values, "charge_full")
    raw_design_charge = number(values, "charge_full_design")
    raw_full_energy = number(values, "energy_full")
    raw_design_energy = number(values, "energy_full_design")
    full_ah = normalize_capacity_ah(raw_full_charge)
    design_ah = normalize_capacity_ah(raw_design_charge)

    if percentage is None:
        percentage = termux.get("percentage", termux.get("level"))

    if temperature is None:
        temperature = normalize_temperature(termux.get("temperature"))

    if voltage is None:
        voltage = normalize_termux_voltage(termux.get("voltage"))

    if current is None:
        current = normalize_current(
            termux.get("current", termux.get("current_average"))
        )

    health_percent = None

    health_source = None

    if (
        raw_full_charge is not None
        and raw_design_charge is not None
        and raw_design_charge > 0
    ):
        health_percent = round(
            min(150.0, raw_full_charge / raw_design_charge * 100),
            1,
        )
        health_source = "charge_full"
    elif (
        raw_full_energy is not None
        and raw_design_energy is not None
        and raw_design_energy > 0
    ):
        health_percent = round(
            min(150.0, raw_full_energy / raw_design_energy * 100),
            1,
        )
        health_source = "energy_full"

    power_watts = None

    if voltage is not None and current is not None:
        power_watts = round(voltage * current, 2)

    charge_control = {
        "supported": False,
        "driver": None,
        "current_limit_percent": None,
        "allowed_limits": sorted(ALLOWED_CHARGE_LIMITS),
        "note": "Kernelul nu expune o limită de încărcare compatibilă.",
    }

    for driver in ("standard", "samsung"):
        raw_limit = number(values, f"limit_{driver}")

        if raw_limit is None or not 50 <= raw_limit <= 100:
            continue

        charge_control = {
            "supported": True,
            "driver": driver,
            "current_limit_percent": int(raw_limit),
            "allowed_limits": sorted(ALLOWED_CHARGE_LIMITS),
            "note": (
                "Limită standard raportată de kernel."
                if driver == "standard"
                else "Limită raportată de driverul Samsung."
            ),
        }
        break

    return {
        "available": bool(values or termux),
        "root_available": root_available,
        "percentage": int(percentage) if percentage is not None else None,
        "temperature_c": temperature,
        "status": values.get("status") or termux.get("status"),
        "health": values.get("health") or termux.get("health"),
        "technology": values.get("technology") or termux.get("technology"),
        "voltage_v": voltage,
        "current_a": current,
        "power_w": power_watts,
        "charge_counter_ah": normalize_capacity_ah(
            number(values, "charge_counter")
        ),
        "full_capacity_ah": full_ah,
        "design_capacity_ah": design_ah,
        "health_percent": health_percent,
        "health_estimate_source": health_source,
        "cycle_count": (
            int(number(values, "cycle_count"))
            if number(values, "cycle_count") is not None
            else None
        ),
        "charge_control": charge_control,
    }


def parse_thermal_sensors(text):
    sensors = []

    for line in text.splitlines():
        fields = line.split("|", 2)

        if len(fields) != 3 or fields[0] != "sensor":
            continue

        try:
            temperature = normalize_temperature(float(fields[2]))
        except ValueError:
            continue

        if temperature is None or not -40 <= temperature <= 150:
            continue

        sensors.append({"name": fields[1].strip(), "temperature_c": temperature})

    return sensors


def select_sensor_temperature(sensors, keywords):
    matches = [
        sensor["temperature_c"]
        for sensor in sensors
        if any(keyword in sensor["name"].lower() for keyword in keywords)
    ]
    return max(matches) if matches else None


def collect_thermal_status(battery_temperature=None):
    try:
        sensors = parse_thermal_sensors(run_root_shell(THERMAL_ROOT_COMMAND))
        root_available = True
    except DevicePowerError:
        sensors = []
        root_available = False

    try:
        service_output = run_root_shell("dumpsys thermalservice", timeout=8)
        root_available = True
    except DevicePowerError:
        service_output = ""

    status_match = re.search(
        r"Thermal\s+Status\s*:\s*(\d+)",
        service_output,
        flags=re.IGNORECASE,
    )
    severity = int(status_match.group(1)) if status_match else None
    cpu_temperature = select_sensor_temperature(
        sensors,
        ("cpu", "soc", "tsens"),
    )
    gpu_temperature = select_sensor_temperature(sensors, ("gpu", "kgsl"))
    skin_temperature = select_sensor_temperature(sensors, ("skin", "quiet"))

    return {
        "available": bool(sensors or severity is not None),
        "root_available": root_available,
        "severity": severity,
        "severity_label": THERMAL_STATUS_LABELS.get(
            severity,
            "Necunoscut" if severity is not None else "Indisponibil",
        ),
        "battery_temperature_c": battery_temperature,
        "cpu_temperature_c": cpu_temperature,
        "gpu_temperature_c": gpu_temperature,
        "skin_temperature_c": skin_temperature,
        "sensors": sorted(
            sensors,
            key=lambda sensor: sensor["temperature_c"],
            reverse=True,
        )[:20],
    }


def apply_charge_limit(driver, limit_percent):
    try:
        limit_percent = int(limit_percent)
    except (TypeError, ValueError) as error:
        raise DevicePowerError("Limita de încărcare este invalidă.") from error

    if limit_percent not in ALLOWED_CHARGE_LIMITS:
        raise DevicePowerError("Sunt permise numai limitele 80, 85 și 100%.")

    path = CHARGE_LIMIT_PATHS.get(driver)

    if path is None:
        raise DevicePowerError("Driverul limitei de încărcare nu este acceptat.")

    command = (
        f"test -e {path} && printf '%s\\n' {limit_percent} > {path} "
        f"&& cat {path}"
    )
    output = run_root_shell(command)

    try:
        applied_value = int(output.strip().splitlines()[-1])
    except (IndexError, ValueError) as error:
        raise DevicePowerError(
            "Kernelul nu a confirmat noua limită de încărcare."
        ) from error

    if applied_value != limit_percent:
        raise DevicePowerError(
            f"Kernelul a raportat limita {applied_value}%, nu {limit_percent}%."
        )

    return applied_value


def collect_power_snapshot():
    battery = collect_battery_health()
    thermal = collect_thermal_status(battery.get("temperature_c"))
    return {"battery": battery, "thermal": thermal}
