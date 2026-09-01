import argparse
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


DATA_DIR = Path.home() / "cloud-in-buzunar-data"
MODEL_DIR = DATA_DIR / "models"
AI_DATA_DIR = DATA_DIR / "ai"
LOG_DIR = DATA_DIR / "logs"
MODE_FILE = AI_DATA_DIR / "model-mode"
PID_FILE = AI_DATA_DIR / "llama-server.pid"
LOG_FILE = LOG_DIR / "llama-server.log"

LLAMA_SERVER = Path(
    "/data/data/com.termux/files/usr/bin/llama-server"
)
LLAMA_HEALTH_URL = "http://127.0.0.1:8081/health"

MODEL_PROFILES = {
    "rapid": {
        "label": "Qwen2.5 1.5B Instruct Q4_K_M",
        "short_label": "Rapid · 1.5B",
        "description": "Răspuns mai rapid și consum redus de resurse.",
        "model_id": "qwen2.5-1.5b-instruct",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    "quality": {
        "label": "Qwen2.5 3B Instruct Q4_K_M",
        "short_label": "Calitate · 3B",
        "description": "Răspunsuri mai bune, dar generate mai lent.",
        "model_id": "qwen2.5-3b-instruct",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
    },
}

SWITCH_LOCK = threading.Lock()


class AiRuntimeError(Exception):
    pass


def ensure_directories():
    AI_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def get_stored_mode():
    try:
        mode = MODE_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        mode = "rapid"

    if mode not in MODEL_PROFILES:
        return "rapid"

    return mode


def get_model_path(mode):
    try:
        profile = MODEL_PROFILES[mode]
    except KeyError as error:
        raise AiRuntimeError("Unknown AI mode") from error

    return MODEL_DIR / profile["filename"]


def get_server_pids():
    result = subprocess.run(
        [
            "pgrep",
            "-f",
            "llama-server.*--port 8081",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    pids = []

    for value in result.stdout.split():
        try:
            pid = int(value)
        except ValueError:
            continue

        if pid != os.getpid():
            pids.append(pid)

    return pids


def read_process_command(pid):
    try:
        command = Path(
            f"/proc/{pid}/cmdline"
        ).read_bytes()
    except (FileNotFoundError, PermissionError, OSError):
        return ""

    return command.replace(b"\0", b" ").decode(
        "utf-8",
        errors="replace",
    )


def detect_running_mode():
    for pid in get_server_pids():
        command = read_process_command(pid)

        for mode, profile in MODEL_PROFILES.items():
            if profile["filename"] in command:
                return mode

    return None


def get_active_mode():
    return detect_running_mode() or get_stored_mode()


def get_active_profile():
    mode = get_active_mode()
    profile = dict(MODEL_PROFILES[mode])
    profile["mode"] = mode

    return profile


def is_healthy(timeout=2):
    try:
        with urlopen(
            LLAMA_HEALTH_URL,
            timeout=timeout,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )
    except (
        URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
    ):
        return False

    return result.get("status") == "ok"


def get_runtime_status():
    profile = get_active_profile()
    pids = get_server_pids()

    return {
        "online": bool(pids) and is_healthy(),
        "mode": profile["mode"],
        "model": profile["label"],
        "pid": pids[0] if pids else None,
    }


def stop_server(timeout=12):
    pids = get_server_pids()

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    deadline = time.monotonic() + timeout

    while get_server_pids() and time.monotonic() < deadline:
        time.sleep(0.25)

    remaining = get_server_pids()

    if remaining:
        raise AiRuntimeError(
            "The current AI model did not stop cleanly"
        )

    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def start_server(mode, timeout=60):
    ensure_directories()

    model_path = get_model_path(mode)

    if not model_path.is_file():
        raise AiRuntimeError(
            f"Model file not found: {model_path}"
        )

    if not LLAMA_SERVER.is_file():
        raise AiRuntimeError(
            f"llama-server not found: {LLAMA_SERVER}"
        )

    with LOG_FILE.open("ab", buffering=0) as log_file:
        process = subprocess.Popen(
            [
                str(LLAMA_SERVER),
                "--model",
                str(model_path),
                "--host",
                "127.0.0.1",
                "--port",
                "8081",
                "--ctx-size",
                "2048",
                "--threads",
                "3" if mode == "rapid" else "2",
                "--parallel",
                "1",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    PID_FILE.write_text(
        f"{process.pid}\n",
        encoding="utf-8",
    )

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AiRuntimeError(
                "llama-server stopped while loading the model"
            )

        if is_healthy():
            return process.pid

        time.sleep(0.5)

    try:
        process.terminate()
    except ProcessLookupError:
        pass

    raise AiRuntimeError("AI model loading timed out")


def switch_model(mode):
    if mode not in MODEL_PROFILES:
        raise AiRuntimeError("Mode must be rapid or quality")

    model_path = get_model_path(mode)

    if not model_path.is_file():
        raise AiRuntimeError(
            f"Model file not found: {model_path}"
        )

    with SWITCH_LOCK:
        previous_mode = get_active_mode()

        if (
            detect_running_mode() == mode
            and is_healthy()
        ):
            MODE_FILE.write_text(
                f"{mode}\n",
                encoding="utf-8",
            )
            return get_runtime_status()

        stop_server()

        try:
            start_server(mode)
        except AiRuntimeError as switch_error:
            rollback_message = ""

            if previous_mode != mode:
                try:
                    start_server(previous_mode)
                    MODE_FILE.write_text(
                        f"{previous_mode}\n",
                        encoding="utf-8",
                    )
                    rollback_message = (
                        " Previous model was restored."
                    )
                except AiRuntimeError:
                    rollback_message = (
                        " Previous model could not be restored."
                    )

            raise AiRuntimeError(
                f"{switch_error}.{rollback_message}"
            ) from switch_error

        MODE_FILE.write_text(
            f"{mode}\n",
            encoding="utf-8",
        )

        return get_runtime_status()


def start_selected_model():
    ensure_directories()

    if get_server_pids() and is_healthy():
        return get_runtime_status()

    if get_server_pids():
        stop_server()

    mode = get_stored_mode()
    start_server(mode)

    return get_runtime_status()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Manage the CloudInBuzunar AI model",
    )
    commands = parser.add_subparsers(dest="command")

    commands.add_parser("start")
    commands.add_parser("stop")
    commands.add_parser("status")

    switch_parser = commands.add_parser("switch")
    switch_parser.add_argument(
        "mode",
        choices=tuple(MODEL_PROFILES),
    )

    return parser


def main():
    parser = build_parser()
    arguments = parser.parse_args()

    try:
        if arguments.command == "start":
            result = start_selected_model()
        elif arguments.command == "stop":
            stop_server()
            result = get_runtime_status()
        elif arguments.command == "status":
            result = get_runtime_status()
        elif arguments.command == "switch":
            result = switch_model(arguments.mode)
        else:
            parser.print_help()
            return 1
    except AiRuntimeError as error:
        print(f"Error: {error}")
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
