import importlib
import os
import sys
import tempfile
import unittest


class RegistrationRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.original_home = os.environ.get("HOME")
        cls.original_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = cls.temporary_directory.name
        os.environ["USERPROFILE"] = cls.temporary_directory.name

        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        cls.database = importlib.import_module("app.database")
        cls.database.initialize_database()
        cls.database.create_user(
            "admin",
            "admin-password",
            role="admin",
        )
        cls.database.create_user(
            "member",
            "member-password",
            role="user",
        )
        cls.main = importlib.import_module("app.main")

    @classmethod
    def tearDownClass(cls):
        for module_name in list(sys.modules):
            if module_name == "app" or module_name.startswith("app."):
                del sys.modules[module_name]

        if cls.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = cls.original_home

        if cls.original_userprofile is None:
            os.environ.pop("USERPROFILE", None)
        else:
            os.environ["USERPROFILE"] = cls.original_userprofile

        cls.temporary_directory.cleanup()

    def setUp(self):
        self.client = self.main.app.test_client()

    def login(self, username, password):
        return self.client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": password,
            },
        )

    def register(
        self,
        username,
        password="new-user-password",
        remote_addr="127.0.0.1",
    ):
        return self.client.post(
            "/api/auth/register",
            json={
                "username": username,
                "password": password,
                "role": "admin",
            },
            environ_overrides={"REMOTE_ADDR": remote_addr},
        )

    def test_registration_waits_for_admin_approval(self):
        response = self.register("pending-user")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "pending")
        login = self.login("pending-user", "new-user-password")
        self.assertEqual(login.status_code, 401)

        connection = self.database.open_database()

        try:
            password_hash = connection.execute(
                """
                SELECT password_hash
                FROM registration_requests
                WHERE username = 'pending-user'
                """
            ).fetchone()["password_hash"]
        finally:
            connection.close()

        self.assertNotEqual(password_hash, "new-user-password")

    def test_admin_approval_creates_regular_user(self):
        registration = self.register("approved-user").get_json()
        self.assertEqual(
            self.login("admin", "admin-password").status_code,
            200,
        )

        response = self.client.post(
            "/api/admin/registrations/"
            f"{registration['id']}/approve"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["user"]["role"], "user")
        self.client.post("/api/auth/logout")
        login = self.login("approved-user", "new-user-password")
        self.assertEqual(login.status_code, 200)

    def test_regular_user_cannot_read_pending_requests(self):
        self.assertEqual(
            self.login("member", "member-password").status_code,
            200,
        )

        response = self.client.get("/api/admin/registrations")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_reject_request(self):
        registration = self.register("rejected-user").get_json()
        self.assertEqual(
            self.login("admin", "admin-password").status_code,
            200,
        )

        response = self.client.delete(
            "/api/admin/registrations/"
            f"{registration['id']}"
        )

        self.assertEqual(response.status_code, 200)
        usernames = {
            request["username"]
            for request in self.database.list_registration_requests()
        }
        self.assertNotIn("rejected-user", usernames)

    def test_invalid_registration_is_rejected(self):
        response = self.register("bad name", "short")

        self.assertEqual(response.status_code, 400)

    def test_dashboard_contains_registration_controls(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="registration-form"', html)
        self.assertIn('id="registration-requests"', html)

    def test_registration_is_rate_limited_per_address(self):
        remote_addr = "10.0.0.50"

        for index in range(5):
            response = self.register(
                f"limited-{index}",
                remote_addr=remote_addr,
            )
            self.assertEqual(response.status_code, 201)

        response = self.register(
            "limited-last",
            remote_addr=remote_addr,
        )
        self.assertEqual(response.status_code, 429)


if __name__ == "__main__":
    unittest.main()
