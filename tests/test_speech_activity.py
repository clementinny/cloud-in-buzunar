import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.speech_activity import detect_speech_activity


class SpeechActivityTest(unittest.TestCase):
    @patch("app.speech_activity.shutil.which", return_value=None)
    def test_reports_unavailable_without_ffmpeg(self, _which):
        self.assertEqual(
            detect_speech_activity("missing.m4a", 20),
            ("unavailable", []),
        )

    @patch("app.speech_activity.subprocess.run")
    @patch("app.speech_activity.shutil.which", return_value="ffmpeg")
    def test_returns_non_silent_start_offsets(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stderr=(
                "silence_start: 0\n"
                "silence_end: 5.2 | silence_duration: 5.2\n"
                "silence_start: 9.1\n"
                "silence_end: 12.4 | silence_duration: 3.3\n"
                "silence_start: 15.8\n"
            ),
        )

        self.assertEqual(
            detect_speech_activity("segment.m4a", 20),
            ("complete", [5, 12]),
        )

    @patch("app.speech_activity.subprocess.run")
    @patch("app.speech_activity.shutil.which", return_value="ffmpeg")
    def test_reports_no_activity_for_a_silent_segment(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stderr="silence_start: 0\n",
        )

        self.assertEqual(
            detect_speech_activity("segment.m4a", 600),
            ("complete", []),
        )


if __name__ == "__main__":
    unittest.main()
