import argparse
import hashlib
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request, session

from app.database import (
    acknowledge_system_alert_events,
    find_monitor_device_by_token_hash,
    find_user_by_id,
    get_system_alert_settings,
    initialize_database,
    list_active_system_alerts,
    list_system_alert_events,
    prune_system_alert_events,
    record_system_alert_event,
    sync_system_alert_conditions,
    update_system_alert_settings,
)


reliability_alerts_blueprint = Blueprint("reliability_alerts", __name__)

BOOLEAN_SETTING_FIELDS = {
    "enabled",
    "alert_server",
    "alert_charger",
    "alert_battery",
    "alert_thermal",
    "alert_storage",
    "alert_services",
}
INTEGER_SETTING_RANGES = {
    "battery_low_percent": (5, 80),
    "storage_warning_percent": (50, 99),
    "cooldown_minutes": (5, 1440),
}
NUMBER_SETTING_RANGES = {
    "thermal_warning_c": (30, 60),
}
ALL_SETTING_FIELDS = (
    BOOLEAN_SETTING_FIELDS
    | set(INTEGER_SETTING_RANGES)
    | set(NUMBER_SETTING_RANGES)
)
ALERT_SEVERITIES = {"warning", "critical", "info"}


def get_session_admin():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user if user["role"] == "admin" else False


def require_alert_admin(view_function):
    def wrapped_view(*args, **kwargs):
        user = get_session_admin()

        if user is None:
            return jsonify({"error": "Authentication required"}), 401

        if user is False:
            return jsonify(
                {"error": "Administrator access required"}
            ), 403

        return view_function(*args, **kwargs)

    wrapped_view.__name__ = view_function.__name__
    return wrapped_view


def hash_device_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def require_alert_device(view_function):
    def wrapped_view(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")

        if not authorization.startswith("Bearer "):
            return jsonify(
                {"error": "Monitor device authentication required"}
            ), 401

        token = authorization[7:].strip()
        device = (
            find_monitor_device_by_token_hash(hash_device_token(token))
            if token
            else None
        )

        if device is None:
            return jsonify(
                {"error": "Monitor device authentication required"}
            ), 401

        g.alert_device = device
        return view_function(*args, **kwargs)

    wrapped_view.__name__ = view_function.__name__
    return wrapped_view


def validate_alert_settings(payload):
    if not isinstance(payload, dict) or set(payload) != ALL_SETTING_FIELDS:
        raise ValueError("Configurația alertelor este incompletă sau invalidă.")

    result = {}

    for field in BOOLEAN_SETTING_FIELDS:
        if type(payload[field]) is not bool:
            raise ValueError(f"Câmpul {field} trebuie să fie boolean.")

        result[field] = payload[field]

    for field, (minimum, maximum) in INTEGER_SETTING_RANGES.items():
        value = payload[field]

        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError(
                f"Câmpul {field} trebuie să fie între {minimum} și {maximum}."
            )

        result[field] = value

    for field, (minimum, maximum) in NUMBER_SETTING_RANGES.items():
        value = payload[field]

        if type(value) not in {int, float} or not minimum <= value <= maximum:
            raise ValueError(
                f"Câmpul {field} trebuie să fie între {minimum} și {maximum}."
            )

        result[field] = float(value)

    return result


def alert_condition(alert_key, category, severity, title, message):
    return {
        "alert_key": alert_key,
        "category": category,
        "severity": severity,
        "title": title,
        "message": message,
    }


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_alert_conditions(status, resources, power, settings):
    if not settings["enabled"]:
        return []

    conditions = []
    services = {
        service.get("id"): service
        for service in status.get("services", [])
    }

    if settings["alert_server"]:
        for service_id in ("web", "database"):
            service = services.get(service_id)

            if service and service.get("state") in {
                "warning",
                "critical",
                "offline",
            }:
                severity = (
                    "critical"
                    if service.get("state") in {"critical", "offline"}
                    else "warning"
                )
                conditions.append(
                    alert_condition(
                        f"server:{service_id}",
                        "server",
                        severity,
                        f"Problemă server: {service.get('name', service_id)}",
                        service.get("summary") or "Serviciul nu răspunde normal.",
                    )
                )

    if settings["alert_services"]:
        for service_id in ("supervisor", "ai", "aria2", "transmission"):
            service = services.get(service_id)

            if (
                service
                and service.get("impact") in {"warning", "critical"}
                and service.get("state") in {
                    "warning",
                    "critical",
                    "offline",
                }
            ):
                conditions.append(
                    alert_condition(
                        f"service:{service_id}",
                        "service",
                        (
                            "critical"
                            if service.get("impact") == "critical"
                            else "warning"
                        ),
                        f"Serviciu indisponibil: {service.get('name', service_id)}",
                        service.get("summary") or "Serviciul necesită atenție.",
                    )
                )

    battery = power.get("battery", {})
    battery_percent = _number(battery.get("percentage"))

    if (
        settings["alert_battery"]
        and battery_percent is not None
        and battery_percent <= settings["battery_low_percent"]
    ):
        conditions.append(
            alert_condition(
                "battery:low",
                "battery",
                "critical" if battery_percent <= 10 else "warning",
                "Baterie descărcată",
                f"Nivelul bateriei este {battery_percent:.0f}%.",
            )
        )

    plugged = str(battery.get("plugged") or "").strip().upper()
    battery_status = str(battery.get("status") or "").strip().upper()

    if (
        settings["alert_charger"]
        and plugged in {"UNPLUGGED", "NONE", "FALSE", "0"}
    ):
        conditions.append(
            alert_condition(
                "charger:unplugged",
                "charger",
                "warning",
                "Încărcător deconectat",
                "Telefonul-server nu mai este conectat la alimentare.",
            )
        )
    elif (
        settings["alert_charger"]
        and plugged
        and plugged not in {"UNPLUGGED", "NONE", "FALSE", "0"}
        and battery_status in {"DISCHARGING", "NOT_CHARGING"}
    ):
        conditions.append(
            alert_condition(
                "charger:not-charging",
                "charger",
                "warning",
                "Telefonul nu se încarcă",
                "Alimentarea este conectată, dar bateria nu raportează încărcare.",
            )
        )

    thermal = power.get("thermal", {})
    temperatures = [
        _number(battery.get("temperature_c")),
        _number(thermal.get("cpu_temperature_c")),
        _number(thermal.get("gpu_temperature_c")),
        _number(thermal.get("skin_temperature_c")),
    ]
    temperatures = [value for value in temperatures if value is not None]
    highest_temperature = max(temperatures) if temperatures else None
    thermal_severity = _number(thermal.get("severity"))

    if settings["alert_thermal"] and (
        (
            highest_temperature is not None
            and highest_temperature >= settings["thermal_warning_c"]
        )
        or (thermal_severity is not None and thermal_severity >= 2)
    ):
        critical = (
            (highest_temperature is not None and highest_temperature >= 47)
            or (thermal_severity is not None and thermal_severity >= 4)
        )
        temperature_text = (
            f" Temperatura maximă citită este {highest_temperature:.1f} °C."
            if highest_temperature is not None
            else ""
        )
        conditions.append(
            alert_condition(
                "thermal:high",
                "thermal",
                "critical" if critical else "warning",
                "Temperatură ridicată",
                "Telefonul-server a depășit pragul termic configurat."
                + temperature_text,
            )
        )

    storage = resources.get("storage", {})
    storage_percent = _number(storage.get("used_percent"))

    if (
        settings["alert_storage"]
        and storage.get("available", storage_percent is not None)
        and storage_percent is not None
        and storage_percent >= settings["storage_warning_percent"]
    ):
        conditions.append(
            alert_condition(
                "storage:full",
                "storage",
                "critical" if storage_percent >= 97 else "warning",
                "Spațiu de stocare redus",
                f"Stocarea este ocupată în proporție de {storage_percent:.1f}%.",
            )
        )

    return conditions


def run_reliability_check(status=None, resources=None, power=None, now=None):
    if status is None or resources is None or power is None:
        from app.device_power import collect_power_snapshot
        from app.resource_monitor import collect_resource_usage
        from app.system_status import collect_system_status

        status = status if status is not None else collect_system_status()
        resources = (
            resources if resources is not None else collect_resource_usage()
        )
        power = power if power is not None else collect_power_snapshot()

    settings = get_system_alert_settings()
    conditions = build_alert_conditions(status, resources, power, settings)
    events = sync_system_alert_conditions(
        conditions,
        settings["cooldown_minutes"],
        now=now,
    )
    prune_system_alert_events()
    return {
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(),
        "active_alerts": list_active_system_alerts(),
        "events": events,
    }


@reliability_alerts_blueprint.get("/api/system/alerts")
@require_alert_admin
def system_alerts_api():
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return jsonify({"error": "Limita este invalidă."}), 400

    if not 1 <= limit <= 500:
        return jsonify({"error": "Limita trebuie să fie între 1 și 500."}), 400

    return jsonify(
        {
            "settings": get_system_alert_settings(),
            "active_alerts": list_active_system_alerts(),
            "alerts": list_system_alert_events(limit=limit),
        }
    )


@reliability_alerts_blueprint.post("/api/system/alerts/settings")
@require_alert_admin
def system_alert_settings_api():
    try:
        settings = validate_alert_settings(request.get_json(silent=True))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    return jsonify(
        {
            "settings": update_system_alert_settings(settings),
            "message": "Configurația alertelor a fost salvată.",
        }
    )


@reliability_alerts_blueprint.post("/api/system/alerts/check")
@require_alert_admin
def system_alert_check_api():
    return jsonify(run_reliability_check())


@reliability_alerts_blueprint.post("/api/system/alerts/test")
@require_alert_admin
def system_alert_test_api():
    condition = alert_condition(
        "test:manual",
        "test",
        "info",
        "Alertă de test CloudInBuzunar",
        "Canalul de notificări funcționează și dispozitivul poate prelua alerta.",
    )
    event_id = record_system_alert_event(condition, event_type="test")
    return jsonify({"id": event_id, **condition}), 201


@reliability_alerts_blueprint.get("/api/system/alerts/feed")
@require_alert_device
def system_alert_feed_api():
    try:
        limit = int(request.args.get("limit", 50))
    except (TypeError, ValueError):
        return jsonify({"error": "Limita este invalidă."}), 400

    if not 1 <= limit <= 100:
        return jsonify({"error": "Limita trebuie să fie între 1 și 100."}), 400

    settings = get_system_alert_settings()
    alerts = list_system_alert_events(
        limit=limit,
        device_id=g.alert_device["id"],
    )
    return jsonify(
        {
            "configuration_version": settings["updated_at"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "active_alerts": list_active_system_alerts(),
            "alerts": alerts,
            "next_after_id": max(
                (alert["id"] for alert in alerts),
                default=0,
            ),
        }
    )


@reliability_alerts_blueprint.post("/api/system/alerts/feed/ack")
@require_alert_device
def system_alert_feed_ack_api():
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict) or set(payload) != {"event_ids"}:
        return jsonify({"error": "Lista evenimentelor este invalidă."}), 400

    event_ids = payload["event_ids"]

    if (
        not isinstance(event_ids, list)
        or len(event_ids) > 100
        or any(type(event_id) is not int or event_id < 1 for event_id in event_ids)
    ):
        return jsonify({"error": "Lista evenimentelor este invalidă."}), 400

    acknowledged = acknowledge_system_alert_events(
        g.alert_device["id"],
        event_ids,
    )
    return jsonify({"acknowledged": acknowledged})


def main():
    parser = argparse.ArgumentParser(
        description="Check CloudInBuzunar reliability alerts"
    )
    parser.add_argument("command", choices=("check",))
    parser.parse_args()
    initialize_database()
    result = run_reliability_check()
    print(
        f"Alert check complete: {len(result['active_alerts'])} active, "
        f"{len(result['events'])} new events"
    )


if __name__ == "__main__":
    main()
