import os
import re
import subprocess
import tempfile
from pathlib import Path


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
AUTOSTART_CONFIG_FILE = DATA_DIR / "autostart.conf"
PROJECT_DIR = Path(__file__).resolve().parents[1]
SERVICE_MANAGER = PROJECT_DIR / "scripts" / "cloud-services.sh"

MANAGED_BOOLEAN_SETTINGS = {
    "START_TRANSMISSION",
}


class ServiceControlError(Exception):
    pass


def read_boolean_setting(name, default=False):
    if name not in MANAGED_BOOLEAN_SETTINGS:
        raise ValueError("Unsupported service setting")

    try:
        lines = AUTOSTART_CONFIG_FILE.read_text(
            encoding="utf-8"
        ).splitlines()
    except FileNotFoundError:
        return default
    except OSError as error:
        raise ServiceControlError(
            "Configurația serviciilor nu poate fi citită."
        ) from error

    setting_pattern = re.compile(
        rf"^\s*{re.escape(name)}\s*=\s*(true|false)\s*$",
        re.IGNORECASE,
    )

    for line in lines:
        match = setting_pattern.match(line)

        if match:
            return match.group(1).lower() == "true"

    return default


def write_boolean_setting(name, enabled):
    if name not in MANAGED_BOOLEAN_SETTINGS:
        raise ValueError("Unsupported service setting")

    try:
        existing_text = AUTOSTART_CONFIG_FILE.read_text(
            encoding="utf-8"
        )
    except FileNotFoundError:
        existing_text = ""
    except OSError as error:
        raise ServiceControlError(
            "Configurația serviciilor nu poate fi citită."
        ) from error

    replacement = f"{name}={'true' if enabled else 'false'}"
    setting_pattern = re.compile(
        rf"^\s*{re.escape(name)}\s*=.*$",
        re.MULTILINE,
    )

    if setting_pattern.search(existing_text):
        updated_text = setting_pattern.sub(
            replacement,
            existing_text,
            count=1,
        )
    else:
        separator = "" if not existing_text else "\n"
        updated_text = (
            existing_text.rstrip("\n")
            + separator
            + replacement
            + "\n"
        )

    AUTOSTART_CONFIG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=AUTOSTART_CONFIG_FILE.parent,
            prefix=".autostart-",
            delete=False,
        ) as temporary_file:
            temporary_file.write(updated_text)
            temporary_path = Path(temporary_file.name)

        temporary_path.chmod(0o600)
        os.replace(temporary_path, AUTOSTART_CONFIG_FILE)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        raise ServiceControlError(
            "Configurația serviciilor nu poate fi salvată."
        ) from error


def transmission_is_enabled():
    return read_boolean_setting(
        "START_TRANSMISSION",
        default=True,
    )


def set_transmission_enabled(enabled):
    enabled = bool(enabled)
    previous_value = transmission_is_enabled()
    write_boolean_setting("START_TRANSMISSION", enabled)
    command = (
        "transmission-start"
        if enabled
        else "transmission-stop"
    )

    try:
        subprocess.run(
            [str(SERVICE_MANAGER), command],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
            timeout=25,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as error:
        if enabled:
            write_boolean_setting(
                "START_TRANSMISSION",
                previous_value,
            )

        action = "pornit" if enabled else "oprit"
        raise ServiceControlError(
            f"Transmission nu a putut fi {action}."
        ) from error

    return enabled
