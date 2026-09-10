import os
import tempfile
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
