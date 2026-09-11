import argparse
import json
import os
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.database import prune_system_metrics, record_system_metric
from app.device_power import (
    DevicePowerError,
    apply_charge_limit,
    collect_power_snapshot,
)
from app.resource_monitor import collect_resource_usage
from app.service_control import PROJECT_DIR, SERVICE_MANAGER


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
POLICY_FILE = DATA_DIR / "thermal-policy.json"
STATE_FILE = DATA_DIR / "runtime" / "thermal-guardian.json"
SUSPENDED_DIR = DATA_DIR / "runtime" / "thermal-suspended"
DEFAULT_POLICY = {
    "enabled": True,
    "warning_temperature_c": 40.0,
    "critical_temperature_c": 43.0,
    "recovery_temperature_c": 37.5,
    "stop_ai": True,
    "stop_transmission": True,
    "stop_aria2_on_critical": True,
    "charge_limit_percent": None,
}
SERVICE_COMMANDS = {
    "ai": ("ai-stop", "ai-start"),
    "transmission": ("transmission-stop", "transmission-start"),
    "aria2": ("aria2-stop", "aria2-start"),
}


class ThermalPolicyError(ValueError):
    pass


def atomic_write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            delete=False,
        ) as temporary_file:
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)

        temporary_path.chmod(0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def get_thermal_policy():
    try:
        payload = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}

    policy = {**DEFAULT_POLICY}

    if isinstance(payload, dict):
        for name in policy:
            if name in payload:
                policy[name] = payload[name]

    return policy


def validate_thermal_policy(payload):
    if not isinstance(payload, dict):
        raise ThermalPolicyError("Configurația termică este invalidă.")

    policy = get_thermal_policy()

    for name in (
        "enabled",
        "stop_ai",
        "stop_transmission",
        "stop_aria2_on_critical",
    ):
        if name in payload:
            if type(payload[name]) is not bool:
                raise ThermalPolicyError(f"Câmpul {name} trebuie să fie boolean.")
            policy[name] = payload[name]

    for name in (
        "warning_temperature_c",
        "critical_temperature_c",
        "recovery_temperature_c",
    ):
        if name in payload:
            try:
                policy[name] = round(float(payload[name]), 1)
            except (TypeError, ValueError) as error:
                raise ThermalPolicyError(
                    f"Câmpul {name} trebuie să fie numeric."
                ) from error

            if not 30 <= policy[name] <= 55:
                raise ThermalPolicyError(
                    "Pragurile termice trebuie să fie între 30 și 55 °C."
                )

    if not (
        policy["recovery_temperature_c"]
        < policy["warning_temperature_c"]
        < policy["critical_temperature_c"]
    ):
        raise ThermalPolicyError(
            "Pragul de revenire trebuie să fie sub avertizare, iar "
            "avertizarea sub pragul critic."
        )

    if "charge_limit_percent" in payload:
        charge_limit = payload["charge_limit_percent"]

        if charge_limit is not None:
            try:
                charge_limit = int(charge_limit)
            except (TypeError, ValueError) as error:
                raise ThermalPolicyError(
                    "Limita de încărcare este invalidă."
                ) from error

            if charge_limit not in {80, 85, 100}:
                raise ThermalPolicyError(
                    "Limita de încărcare trebuie să fie 80, 85 sau 100%."
                )

        policy["charge_limit_percent"] = charge_limit

    return policy


def save_thermal_policy(payload):
    policy = validate_thermal_policy(payload)
    atomic_write_json(POLICY_FILE, policy)
    return policy


def get_guardian_status():
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}

    suspended = sorted(
        path.name for path in SUSPENDED_DIR.glob("*") if path.is_file()
    ) if SUSPENDED_DIR.is_dir() else []

    return {
        "level": payload.get("level", "unknown"),
        "message": payload.get(
            "message",
            "Guardianul nu a înregistrat încă nicio verificare.",
        ),
        "checked_at": payload.get("checked_at"),
        "suspended_services": suspended,
        "last_error": payload.get("last_error"),
    }


def run_service_command(service_id, action):
    commands = SERVICE_COMMANDS.get(service_id)

    if commands is None:
        return False

    command = commands[0] if action == "stop" else commands[1]

    try:
        result = subprocess.run(
            [str(SERVICE_MANAGER), command],
            cwd=PROJECT_DIR,
            capture_output=True,
            check=False,
            text=True,
            timeout=80,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return result.returncode == 0


def suspend_service(service_id):
    try:
        SUSPENDED_DIR.mkdir(parents=True, exist_ok=True)
        marker = SUSPENDED_DIR / service_id
        marker.write_text(
            datetime.now(timezone.utc).isoformat(),
            encoding="utf-8",
        )
        marker.chmod(0o600)
    except OSError:
        return False

    if not run_service_command(service_id, "stop"):
        marker.unlink(missing_ok=True)
        return False

    return True


def recover_suspended_services():
    if not SUSPENDED_DIR.is_dir():
        return []

    recovered = []

    for marker in sorted(SUSPENDED_DIR.iterdir()):
        if marker.name not in SERVICE_COMMANDS or not marker.is_file():
            continue

        if run_service_command(marker.name, "start"):
            marker.unlink(missing_ok=True)
            recovered.append(marker.name)

    return recovered


def determine_thermal_level(policy, power):
    thermal = power.get("thermal", {})
    battery = power.get("battery", {})
    severity = thermal.get("severity")
    battery_temperature = battery.get("temperature_c")
    cpu_temperature = thermal.get("cpu_temperature_c")
    gpu_temperature = thermal.get("gpu_temperature_c")
    skin_temperature = thermal.get("skin_temperature_c")
    readings = (
        severity,
        battery_temperature,
        cpu_temperature,
        gpu_temperature,
        skin_temperature,
    )

    if all(value is None for value in readings):
        return "unknown"

    if (
        (severity is not None and severity >= 3)
        or (
            battery_temperature is not None
            and battery_temperature >= policy["critical_temperature_c"]
        )
        or (skin_temperature is not None and skin_temperature >= 45)
        or (cpu_temperature is not None and cpu_temperature >= 90)
        or (gpu_temperature is not None and gpu_temperature >= 90)
    ):
        return "critical"

    if (
        (severity is not None and severity >= 2)
        or (
            battery_temperature is not None
            and battery_temperature >= policy["warning_temperature_c"]
        )
        or (skin_temperature is not None and skin_temperature >= 42)
        or (cpu_temperature is not None and cpu_temperature >= 80)
        or (gpu_temperature is not None and gpu_temperature >= 80)
    ):
        return "warning"

    return "normal"


def temperatures_are_recovered(policy, power):
    thermal = power.get("thermal", {})
    battery = power.get("battery", {})
    severity = thermal.get("severity")
    limits = (
        (battery.get("temperature_c"), policy["recovery_temperature_c"]),
        (thermal.get("skin_temperature_c"), 39),
        (thermal.get("cpu_temperature_c"), 72),
        (thermal.get("gpu_temperature_c"), 72),
    )

    if severity is not None and severity >= 2:
        return False

    if severity is None and all(value is None for value, _limit in limits):
        return False

    return all(value is None or value <= limit for value, limit in limits)


def build_history_metric(resources, power, recorded_at):
    battery = power.get("battery", {})
    thermal = power.get("thermal", {})
    return {
        "recorded_at": recorded_at,
        "cpu_usage_percent": resources.get("cpu", {}).get("usage_percent"),
        "gpu_usage_percent": resources.get("gpu", {}).get("usage_percent"),
        "battery_temperature_c": battery.get("temperature_c"),
        "cpu_temperature_c": thermal.get("cpu_temperature_c"),
        "gpu_temperature_c": thermal.get("gpu_temperature_c"),
        "skin_temperature_c": thermal.get("skin_temperature_c"),
        "thermal_severity": thermal.get("severity"),
        "battery_percent": battery.get("percentage"),
        "voltage_v": battery.get("voltage_v"),
        "current_a": battery.get("current_a"),
        "power_w": battery.get("power_w"),
    }


def run_guardian_check():
    checked_at = datetime.now(timezone.utc).isoformat()
    policy = get_thermal_policy()
    resources = collect_resource_usage(0.2)
    power = collect_power_snapshot()
    level = determine_thermal_level(policy, power)
    running = {
        service["id"]
        for service in resources.get("managed_services", [])
        if service.get("running")
    }
    actions = []
    errors = []

    try:
        record_system_metric(build_history_metric(resources, power, checked_at))
        prune_system_metrics(168)
    except sqlite3.Error as error:
        errors.append(f"Istoricul nu a putut fi salvat: {error}")

    battery = power.get("battery", {})
    charge_control = battery.get("charge_control", {})
    desired_limit = policy.get("charge_limit_percent")

    if (
        desired_limit is not None
        and charge_control.get("supported")
        and charge_control.get("current_limit_percent") != desired_limit
    ):
        try:
            apply_charge_limit(charge_control["driver"], desired_limit)
            actions.append(f"limită încărcare {desired_limit}%")
        except DevicePowerError as error:
            errors.append(str(error))

    if not policy["enabled"]:
        recovered = recover_suspended_services()
        actions.extend(f"repornit {service}" for service in recovered)
        message = "Protecția automată este dezactivată."
        level = "disabled"
    elif level in {"warning", "critical"}:
        targets = []

        if policy["stop_ai"]:
            targets.append("ai")
        if policy["stop_transmission"]:
            targets.append("transmission")
        if level == "critical" and policy["stop_aria2_on_critical"]:
            targets.append("aria2")

        for service_id in targets:
            if service_id not in running:
                continue

            if suspend_service(service_id):
                actions.append(f"oprit {service_id}")
            else:
                errors.append(f"{service_id} nu a putut fi suspendat")

        message = (
            "Temperatură critică: sarcinile grele au fost suspendate."
            if level == "critical"
            else "Telefon cald: AI și descărcările grele sunt suspendate."
        )
    elif level == "normal" and temperatures_are_recovered(policy, power):
        recovered = recover_suspended_services()
        actions.extend(f"repornit {service}" for service in recovered)
        message = (
            "Temperaturile au revenit la normal; serviciile suspendate "
            "au fost repornite."
            if recovered
            else "Temperaturile sunt în limite normale."
        )
    elif level == "normal":
        level = "recovering"
        message = "Telefonul se răcește; serviciile rămân suspendate."
    else:
        message = (
            "Datele termice sunt momentan indisponibile; serviciile "
            "nu sunt modificate."
        )

    state = {
        "checked_at": checked_at,
        "level": level,
        "message": message,
        "actions": actions,
        "last_error": "; ".join(errors) if errors else None,
    }
    atomic_write_json(STATE_FILE, state)
    return {**state, "policy": policy, "power": power}


def main():
    parser = argparse.ArgumentParser(
        description="Monitorizează și protejează termic CloudInBuzunar"
    )
    parser.add_argument("command", choices=("check", "status"))
    arguments = parser.parse_args()

    if arguments.command == "check":
        print(json.dumps(run_guardian_check(), ensure_ascii=False))
    else:
        print(json.dumps(get_guardian_status(), ensure_ascii=False))


if __name__ == "__main__":
    main()
