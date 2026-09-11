import re
import shutil
import subprocess


SILENCE_PATTERN = re.compile(
    r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)"
)
SILENCE_THRESHOLD = "-38dB"
MINIMUM_SILENCE_SECONDS = 0.8
MINIMUM_ACTIVITY_SECONDS = 0.8
MAXIMUM_EVENTS = 300


def speech_analysis_available():
    return shutil.which("ffmpeg") is not None


def detect_speech_activity(recording_path, duration_seconds):
    ffmpeg = shutil.which("ffmpeg")

    if ffmpeg is None:
        return "unavailable", []

    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-threads",
                "1",
                "-i",
                str(recording_path),
                "-vn",
                "-af",
                (
                    "silencedetect="
                    f"noise={SILENCE_THRESHOLD}:"
                    f"d={MINIMUM_SILENCE_SECONDS}"
                ),
                "-f",
                "null",
                "-",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "failed", []

    if result.returncode != 0:
        return "failed", []

    duration = max(0.0, float(duration_seconds))
    silence_intervals = []
    silence_started_at = None

    for match in SILENCE_PATTERN.finditer(result.stderr):
        event_type = match.group(1)
        timestamp = max(0.0, min(duration, float(match.group(2))))

        if event_type == "start":
            silence_started_at = timestamp
        elif silence_started_at is not None:
            silence_intervals.append(
                (silence_started_at, max(silence_started_at, timestamp))
            )
            silence_started_at = None

    if silence_started_at is not None:
        silence_intervals.append((silence_started_at, duration))

    activity_starts = []
    activity_cursor = 0.0

    for silence_start, silence_end in silence_intervals:
        if silence_start - activity_cursor >= MINIMUM_ACTIVITY_SECONDS:
            activity_starts.append(round(activity_cursor))

        activity_cursor = max(activity_cursor, silence_end)

    if duration - activity_cursor >= MINIMUM_ACTIVITY_SECONDS:
        activity_starts.append(round(activity_cursor))

    unique_starts = []

    for timestamp in activity_starts:
        safe_timestamp = max(0, min(int(duration), int(timestamp)))

        if not unique_starts or safe_timestamp != unique_starts[-1]:
            unique_starts.append(safe_timestamp)

        if len(unique_starts) >= MAXIMUM_EVENTS:
            break

    return "complete", unique_starts
