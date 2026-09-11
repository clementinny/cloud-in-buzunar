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

        audio_filter = run.call_args.args[0][
            run.call_args.args[0].index("-af") + 1
        ]
        self.assertIn("highpass=f=120", audio_filter)
        self.assertIn("lowpass=f=3800", audio_filter)
        self.assertIn("noise=-30dB", audio_filter)

    @patch("app.speech_activity.subprocess.run")
    @patch("app.speech_activity.shutil.which", return_value="ffmpeg")
    def test_ignores_short_startup_noise(self, _which, run):
        run.return_value = SimpleNamespace(
            returncode=0,
            stderr=(
                "silence_start: 1.1\n"
                "silence_end: 3.8 | silence_duration: 2.7\n"
                "silence_start: 6.2\n"
            ),
        )

        self.assertEqual(
            detect_speech_activity("segment.m4a", 8),
            ("complete", [4]),
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
