import io
import os
import tempfile
import time
import unittest


class MonitorDevicePairingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_home = tempfile.TemporaryDirectory()
        os.environ["HOME"] = cls.temporary_home.name
        os.environ["USERPROFILE"] = cls.temporary_home.name

        from app.database import create_user
        from app.main import app

        create_user(
            "monitor-admin",
            "correct-horse-battery",
            role="admin",
        )
        cls.app = app

    @classmethod
    def tearDownClass(cls):
        cls.temporary_home.cleanup()

    def test_single_use_pairing_code_authorizes_native_source(self):
        admin_client = self.app.test_client()
        login = admin_client.post(
            "/api/auth/login",
            json={
                "username": "monitor-admin",
                "password": "correct-horse-battery",
            },
        )
        self.assertEqual(login.status_code, 200)

        pairing_response = admin_client.post(
            "/api/monitor/devices/pairing-code"
        )
        self.assertEqual(pairing_response.status_code, 201)
        pairing_code = pairing_response.get_json()["code"]

        device_client = self.app.test_client()
        pair_response = device_client.post(
            "/api/monitor/devices/pair",
            json={
                "code": pairing_code,
                "device_name": "Test Android",
            },
        )
        self.assertEqual(pair_response.status_code, 201)
        token = pair_response.get_json()["token"]

        reused_code = device_client.post(
            "/api/monitor/devices/pair",
            json={
                "code": pairing_code,
                "device_name": "Second Android",
            },
        )
        self.assertEqual(reused_code.status_code, 401)

        source_id = "native-source-1234567890"
        arm_response = device_client.post(
            "/api/monitor/source/arm",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_id": source_id,
                "camera_facing": "environment",
            },
        )
        self.assertEqual(arm_response.status_code, 201)

        camera_response = admin_client.post(
            "/api/monitor/control",
            json={
                "state": "live",
                "camera_facing": "user",
            },
        )
        self.assertEqual(camera_response.status_code, 200)
        self.assertEqual(
            camera_response.get_json()["camera_facing"],
            "user",
        )

        poll_response = device_client.post(
            "/api/monitor/source/poll",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_id": source_id,
                "actual_state": "armed",
            },
        )
        self.assertEqual(poll_response.status_code, 200)
        self.assertEqual(
            poll_response.get_json()["camera_facing"],
            "user",
        )

        stop_live_response = admin_client.post(
            "/api/monitor/control",
            json={"state": "armed"},
        )
        self.assertEqual(stop_live_response.status_code, 200)

        recording_response = admin_client.post(
            "/api/monitor/recordings/control",
            json={
                "mode": "audio",
                "retention_hours": 48,
                "camera_facing": "environment",
            },
        )
        self.assertEqual(recording_response.status_code, 200)
        self.assertEqual(
            recording_response.get_json()["desired_mode"],
            "audio",
        )

        recording_poll = device_client.post(
            "/api/monitor/source/poll",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_id": source_id,
                "actual_state": "armed",
                "recording_mode": "audio",
            },
        )
        self.assertEqual(recording_poll.status_code, 200)
        self.assertEqual(
            recording_poll.get_json()["recording_mode"],
            "audio",
        )
        self.assertEqual(
            recording_poll.get_json()["recording_camera_facing"],
            "environment",
        )

        live_while_recording_response = admin_client.post(
            "/api/monitor/control",
            json={
                "state": "live",
                "camera_facing": "user",
            },
        )
        self.assertEqual(live_while_recording_response.status_code, 200)

        live_poll = device_client.post(
            "/api/monitor/source/poll",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "source_id": source_id,
                "actual_state": "armed",
                "recording_mode": "off",
            },
        )
        self.assertEqual(live_poll.status_code, 200)
        self.assertEqual(
            live_poll.get_json()["desired_state"],
            "live",
        )
        self.assertEqual(
            live_poll.get_json()["recording_mode"],
            "audio",
        )

        recording_end_ms = int(time.time() * 1000)
        recording_start_ms = recording_end_ms - 10 * 60 * 1000

        upload_response = device_client.post(
            "/api/monitor/recordings",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "mode": "audio",
                "container": "webm",
                "camera_facing": "",
                "started_at_ms": str(recording_start_ms),
                "ended_at_ms": str(recording_end_ms),
                "recording": (
                    io.BytesIO(b"test-aac-segment"),
                    "segment.webm",
                ),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(upload_response.status_code, 201)
        recording_id = upload_response.get_json()["id"]

        recording_list = admin_client.get(
            "/api/monitor/recordings"
        )
        self.assertEqual(recording_list.status_code, 200)
        self.assertEqual(recording_list.get_json()["count"], 1)
        self.assertEqual(
            recording_list.get_json()["recordings"][0]["container"],
            "webm",
        )

        playback_response = admin_client.get(
            f"/api/monitor/recordings/{recording_id}"
        )
        self.assertEqual(playback_response.status_code, 200)
        self.assertEqual(
            playback_response.content_type,
            "audio/webm",
        )
        self.assertEqual(playback_response.data, b"test-aac-segment")
        playback_response.close()

        rejected_response = device_client.post(
            "/api/monitor/source/poll",
            headers={"Authorization": "Bearer invalid-token"},
            json={
                "source_id": source_id,
                "actual_state": "armed",
            },
        )
        self.assertEqual(rejected_response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
