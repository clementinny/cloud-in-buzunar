import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    session,
    url_for,
)

from app.ai_runtime import get_runtime_status
from app.database import (
    DATABASE_PATH,
    find_user_by_id,
    get_active_monitor_source,
    get_monitor_recording_settings,
)
from app.downloads import (
    Aria2Error,
    TransmissionError,
    aria2_call,
    transmission_call,
)
from app.speech_activity import speech_analysis_available


system_status_blueprint = Blueprint("system_status", __name__)

DATA_DIR = Path.home() / "cloud-in-buzunar-data"
BACKUP_DIR = DATA_DIR / "backups"
SERVER_STARTED_AT = time.monotonic()


def get_session_user():
    user_id = session.get("user_id")

    if user_id is None:
        return None

    user = find_user_by_id(user_id)

    if user is None or not user["is_active"]:
        session.clear()
        return None

    return user


def require_status_admin(view_function):
    @wraps(view_function)
    def wrapped_view(*args, **kwargs):
        user = get_session_user()

        if user is None:
            return jsonify({"error": "Authentication required"}), 401

        if user["role"] != "admin":
            return jsonify(
                {"error": "Administrator access required"}
            ), 403

        return view_function(*args, **kwargs)

    return wrapped_view


def format_bytes(value):
    size = float(max(0, value))
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]

    for unit in units:
        if size < 1024 or unit == units[-1]:
            break

        size /= 1024

    precision = 0 if unit == "B" else 1
    return f"{size:.{precision}f} {unit}"


def format_duration(seconds):
    total_seconds = max(0, int(seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days:
        return f"{days}z {hours}h"

    if hours:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


def service_result(
    service_id,
    name,
    state,
    summary,
    metrics=None,
    impact="none",
):
    return {
        "id": service_id,
        "name": name,
        "state": state,
        "summary": summary,
        "metrics": metrics or [],
        "impact": impact,
    }


def metric(label, value):
    return {"label": label, "value": str(value)}


def read_system_uptime():
    try:
        return float(
            Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        )
    except (OSError, ValueError, IndexError):
        return time.monotonic() - SERVER_STARTED_AT


def collect_web_service():
    try:
        load_average = os.getloadavg()[0]
        load_value = f"{load_average:.2f}"
    except (AttributeError, OSError):
        load_value = "Indisponibil"

    return service_result(
        "web",
        "Server web",
        "healthy",
        "Aplicația Flask/Gunicorn răspunde.",
        [
            metric("PID worker", os.getpid()),
            metric("Uptime dispozitiv", format_duration(read_system_uptime())),
            metric("Load 1 minut", load_value),
        ],
        impact="critical",
    )


def collect_database_service():
    started_at = time.monotonic()

    try:
        connection = sqlite3.connect(DATABASE_PATH, timeout=2)

        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()

        latency_ms = (time.monotonic() - started_at) * 1000
        size = DATABASE_PATH.stat().st_size
        return service_result(
            "database",
            "Bază de date",
            "healthy",
            "SQLite este accesibilă și acceptă interogări.",
            [
                metric("Dimensiune", format_bytes(size)),
                metric("Verificare", f"{latency_ms:.0f} ms"),
            ],
            impact="critical",
        )
    except (OSError, sqlite3.Error) as error:
        return service_result(
            "database",
            "Bază de date",
            "offline",
            f"SQLite nu poate fi verificată: {error}",
            impact="critical",
        )


def collect_storage_service():
    try:
        usage = shutil.disk_usage(DATA_DIR)
    except OSError as error:
        return service_result(
            "storage",
            "Stocare",
            "offline",
            f"Spațiul de stocare nu poate fi citit: {error}",
            impact="critical",
        )

    used = usage.total - usage.free
    used_percent = used / usage.total * 100 if usage.total else 0

    if used_percent >= 95:
        state = "critical"
        summary = "Spațiul este aproape complet ocupat."
    elif used_percent >= 85:
        state = "warning"
        summary = "Spațiul liber începe să fie redus."
    else:
        state = "healthy"
        summary = "Există suficient spațiu liber."

    return service_result(
        "storage",
        "Stocare",
        state,
        summary,
        [
            metric("Liber", format_bytes(usage.free)),
            metric("Folosit", f"{used_percent:.1f}%"),
            metric("Total", format_bytes(usage.total)),
        ],
        impact="critical",
    )


def read_meminfo():
    values = {}

    for line in Path("/proc/meminfo").read_text(
        encoding="utf-8"
    ).splitlines():
        name, raw_value = line.split(":", 1)
        values[name] = int(raw_value.strip().split()[0]) * 1024

    return values


def collect_memory_service():
    try:
        memory = read_meminfo()
        total = memory["MemTotal"]
        available = memory["MemAvailable"]
        swap_total = memory.get("SwapTotal", 0)
        swap_free = memory.get("SwapFree", 0)
    except (OSError, ValueError, KeyError, IndexError):
        return service_result(
            "memory",
            "Memorie",
            "unavailable",
            "Datele RAM nu sunt disponibile în acest mediu.",
        )

    available_percent = available / total * 100 if total else 0

    if available_percent < 7:
        state = "critical"
        summary = "Memoria disponibilă este critic de redusă."
    elif available_percent < 15:
        state = "warning"
        summary = "Memoria disponibilă este redusă."
    else:
        state = "healthy"
        summary = "Memoria disponibilă este în limite normale."

    metrics = [
        metric("Disponibil", format_bytes(available)),
        metric("Total RAM", format_bytes(total)),
    ]

    if swap_total:
        metrics.append(
            metric("Swap folosit", format_bytes(swap_total - swap_free))
        )

    return service_result(
        "memory",
        "Memorie",
        state,
        summary,
        metrics,
        impact="critical",
    )


def read_number(path):
    return float(Path(path).read_text(encoding="utf-8").strip())


def collect_battery_from_sysfs():
    base = Path("/sys/class/power_supply/battery")

    if not base.is_dir():
        return None

    result = {}

    try:
        result["percentage"] = int(read_number(base / "capacity"))
    except (OSError, ValueError):
        pass

    try:
        raw_temperature = read_number(base / "temp")
        if raw_temperature > 1000:
            raw_temperature /= 1000
        elif raw_temperature > 100:
            raw_temperature /= 10

        result["temperature"] = raw_temperature
    except (OSError, ValueError):
        pass

    try:
        result["status"] = (base / "status").read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        pass

    return result or None


def collect_battery_from_termux():
    command = shutil.which("termux-battery-status")

    if command is None:
        return None

    try:
        result = subprocess.run(
            [command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            check=False,
        )
        payload = json.loads(result.stdout)
    except (
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        return None

    if result.returncode != 0 or not isinstance(payload, dict):
        return None

    return payload


def collect_battery_service():
    battery = collect_battery_from_sysfs()

    if not battery or "temperature" not in battery:
        termux_battery = collect_battery_from_termux()

        if termux_battery:
            battery = {**(battery or {}), **termux_battery}

    if not battery:
        return service_result(
            "battery",
            "Baterie și temperatură",
            "unavailable",
            "Datele bateriei nu sunt disponibile.",
        )

    temperature = battery.get("temperature")

    try:
        temperature = float(temperature)
    except (TypeError, ValueError):
        temperature = None

    if temperature is not None and temperature >= 45:
        state = "critical"
        summary = "Telefonul este prea fierbinte; oprește sarcinile grele."
    elif temperature is not None and temperature >= 40:
        state = "warning"
        summary = "Telefonul este cald; urmărește temperatura."
    else:
        state = "healthy"
        summary = "Temperatura bateriei este normală."

    metrics = []

    if battery.get("percentage") is not None:
        metrics.append(metric("Încărcare", f"{battery['percentage']}%"))

    if temperature is not None:
        metrics.append(metric("Temperatură", f"{temperature:.1f} °C"))

    if battery.get("status"):
        metrics.append(metric("Stare", battery["status"]))

    return service_result(
        "battery",
        "Baterie și temperatură",
        state,
        summary,
        metrics,
        impact="critical",
    )


def collect_backup_service():
    try:
        archives = sorted(
            BACKUP_DIR.glob("cloud-in-buzunar-*.tar.gz"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError as error:
        return service_result(
            "backup",
            "Backup",
            "warning",
            f"Directorul copiilor nu poate fi citit: {error}",
            impact="warning",
        )

    if not archives:
        return service_result(
            "backup",
            "Backup",
            "warning",
            "Nu există nicio copie de siguranță.",
            impact="warning",
        )

    newest = archives[0]
    newest_time = datetime.fromtimestamp(
        newest.stat().st_mtime,
        timezone.utc,
    )
    age = datetime.now(timezone.utc) - newest_time
    total_size = sum(path.stat().st_size for path in archives)
    stale = age.total_seconds() > 36 * 60 * 60

    return service_result(
        "backup",
        "Backup",
        "warning" if stale else "healthy",
        (
            "Ultima copie este mai veche de 36 de ore."
            if stale
            else "Ultima copie de siguranță este recentă."
        ),
        [
            metric("Ultimul", format_duration(age.total_seconds()) + " în urmă"),
            metric("Copii păstrate", len(archives)),
            metric("Spațiu ocupat", format_bytes(total_size)),
        ],
        impact="warning",
    )


def port_is_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.7):
            return True
    except OSError:
        return False


def collect_aria2_service():
    if not port_is_open(6800):
        return service_result(
            "aria2",
            "aria2",
            "offline",
            "Serviciul pentru linkuri HTTP și magnet nu răspunde.",
            impact="warning",
        )

    try:
        version = aria2_call("getVersion") or {}
        return service_result(
            "aria2",
            "aria2",
            "healthy",
            "Serviciul de descărcări este conectat.",
            [metric("Versiune", version.get("version", "Necunoscută"))],
            impact="warning",
        )
    except Aria2Error as error:
        return service_result(
            "aria2",
            "aria2",
            "warning",
            f"Portul răspunde, dar RPC-ul a raportat: {error}",
            impact="warning",
        )


def collect_transmission_service():
    if not port_is_open(9091):
        return service_result(
            "transmission",
            "Transmission",
            "offline",
            "Serviciul BitTorrent nu răspunde.",
            impact="warning",
        )

    try:
        details = transmission_call("session_get") or {}
        return service_result(
            "transmission",
            "Transmission",
            "healthy",
            "Serviciul BitTorrent este conectat.",
            [
                metric(
                    "Versiune",
                    details.get("version", "Necunoscută"),
                )
            ],
            impact="warning",
        )
    except TransmissionError as error:
        return service_result(
            "transmission",
            "Transmission",
            "warning",
            f"Portul răspunde, dar RPC-ul a raportat: {error}",
            impact="warning",
        )


def collect_ai_service():
    try:
        status = get_runtime_status()
    except (OSError, ValueError) as error:
        return service_result(
            "ai",
            "AI local",
            "warning",
            f"Starea AI nu poate fi citită: {error}",
            impact="warning",
        )

    if not status["online"]:
        return service_result(
            "ai",
            "AI local",
            "idle",
            "Modelul este oprit pentru a economisi resurse.",
            [metric("Model pregătit", status["model"])],
        )

    return service_result(
        "ai",
        "AI local",
        "healthy",
        "llama.cpp răspunde pe telefon.",
        [
            metric("Model", status["model"]),
            metric("PID", status["pid"]),
        ],
    )


def collect_monitor_service():
    try:
        source = get_active_monitor_source()
        recording = get_monitor_recording_settings()
    except (OSError, sqlite3.Error) as error:
        return service_result(
            "monitor",
            "Monitor Android",
            "warning",
            f"Starea Monitorului nu poate fi citită: {error}",
            impact="warning",
        )

    recording = recording or {
        "desired_mode": "off",
        "actual_mode": "off",
    }
    speech_status = (
        "activă" if speech_analysis_available() else "FFmpeg lipsește"
    )

    if source is None:
        return service_result(
            "monitor",
            "Monitor Android",
            "idle",
            "Aplicația Android nu este armată momentan.",
            [
                metric("REC configurat", recording["desired_mode"]),
                metric("Analiză vorbire", speech_status),
            ],
        )

    source_state = source["actual_state"]
    state = "warning" if source_state == "error" else "healthy"
    summary = (
        source["error_message"]
        if source_state == "error" and source["error_message"]
        else "Aplicația Android este armată și comunică cu serverul."
    )

    return service_result(
        "monitor",
        "Monitor Android",
        state,
        summary,
        [
            metric("Sursă", source_state),
            metric("REC dorit", recording["desired_mode"]),
            metric("REC activ", recording["actual_mode"]),
            metric("Analiză vorbire", speech_status),
        ],
        impact="warning",
    )


STATUS_COLLECTORS = [
    collect_web_service,
    collect_database_service,
    collect_storage_service,
    collect_memory_service,
    collect_battery_service,
    collect_backup_service,
    collect_aria2_service,
    collect_transmission_service,
    collect_ai_service,
    collect_monitor_service,
]
STATUS_ORDER = [
    "web",
    "database",
    "storage",
    "memory",
    "battery",
    "backup",
    "aria2",
    "transmission",
    "ai",
    "monitor",
]


def collect_system_status():
    results = {}

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(collector): collector
            for collector in STATUS_COLLECTORS
        }

        for future in as_completed(futures):
            collector = futures[future]

            try:
                result = future.result()
            except Exception as error:
                service_id = collector.__name__.removeprefix(
                    "collect_"
                ).removesuffix("_service")
                result = service_result(
                    service_id,
                    service_id.capitalize(),
                    "warning",
                    f"Verificarea a eșuat: {error}",
                    impact="warning",
                )

            results[result["id"]] = result

    services = [results.get(service_id) for service_id in STATUS_ORDER]
    services = [service for service in services if service is not None]

    overall = "healthy"

    for service in services:
        if (
            service["impact"] == "critical"
            and service["state"] in {"critical", "offline"}
        ):
            overall = "critical"
            break

        if (
            service["impact"] in {"critical", "warning"}
            and service["state"] in {"warning", "critical", "offline"}
        ):
            overall = "warning"

    summaries = {
        "healthy": "Toate serviciile verificate funcționează normal.",
        "warning": "Serverul funcționează, dar există elemente de verificat.",
        "critical": "Un serviciu esențial necesită intervenție.",
    }

    return {
        "overall": overall,
        "summary": summaries[overall],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "services": services,
    }


@system_status_blueprint.get("/status")
def system_status_page():
    user = get_session_user()

    if user is None:
        return redirect(url_for("dashboard"))

    if user["role"] != "admin":
        abort(403)

    return render_template("status.html")


@system_status_blueprint.get("/api/system/status")
@require_status_admin
def system_status_api():
    return jsonify(collect_system_status())
