import importlib
import os
import sys
import tarfile
import tempfile
import unittest


class MessagingRoutesTest(unittest.TestCase):
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
            "alice",
            "alice-password",
            role="user",
        )
        cls.database.create_user(
            "bob",
            "bob-password",
            role="user",
        )
        cls.database.create_user(
            "admin",
            "admin-password",
            role="admin",
        )
        cls.database.create_user(
            "inactive",
            "inactive-password",
            role="user",
        )
        cls.database.set_user_active("inactive", False)

        cls.users = {
            username: cls.database.find_user_by_username(username)
            for username in ("alice", "bob", "admin", "inactive")
        }
        cls.main = importlib.import_module("app.main")
        cls.message_crypto = importlib.import_module(
            "app.message_crypto"
        )
        cls.backup = importlib.import_module("app.backup")

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
        connection = self.database.open_database()

        try:
            connection.execute("DELETE FROM private_messages")
            connection.commit()
        finally:
            connection.close()

    def login(self, username):
        return self.client.post(
            "/api/auth/login",
            json={
                "username": username,
                "password": f"{username}-password",
            },
        )

    def send_to(self, username, content):
        contact_id = self.users[username]["id"]
        return self.client.post(
            f"/api/messages/conversations/{contact_id}",
            json={"content": content},
        )

    def test_api_requires_authentication(self):
        response = self.client.get("/api/messages/contacts")

        self.assertEqual(response.status_code, 401)

    def test_messages_page_redirects_guests(self):
        response = self.client.get("/messages")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))

    def test_active_user_can_open_messages_page(self):
        self.assertEqual(self.login("alice").status_code, 200)

        response = self.client.get("/messages")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="message-form"', response.get_data(as_text=True))

    def test_message_is_encrypted_at_rest(self):
        self.assertEqual(self.login("alice").status_code, 200)
        plaintext = "Mesaj secret pentru Bob"

        response = self.send_to("bob", plaintext)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["message"]["content"],
            plaintext,
        )

        connection = self.database.open_database()

        try:
            stored_content = connection.execute(
                "SELECT content FROM private_messages"
            ).fetchone()["content"]
        finally:
            connection.close()

        self.assertNotEqual(stored_content, plaintext)
        self.assertTrue(
            stored_content.startswith(
                "aes256ctr-hmacsha256:v1:"
            )
        )

    def test_plaintext_message_schema_is_migrated(self):
        connection = self.database.open_database()

        try:
            connection.execute(
                "DROP INDEX IF EXISTS private_messages_conversation"
            )
            connection.execute(
                "DROP INDEX IF EXISTS private_messages_unread"
            )
            connection.execute("DROP TABLE private_messages")
            connection.execute(
                """
                CREATE TABLE private_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    content TEXT NOT NULL
                        CHECK (length(content) BETWEEN 1 AND 2000),
                    created_at TEXT NOT NULL,
                    read_at TEXT,
                    CHECK (sender_id != recipient_id),
                    FOREIGN KEY (sender_id) REFERENCES users(id),
                    FOREIGN KEY (recipient_id) REFERENCES users(id)
                )
                """
            )
            connection.execute(
                """
                INSERT INTO private_messages (
                    sender_id,
                    recipient_id,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    self.users["alice"]["id"],
                    self.users["bob"]["id"],
                    "mesaj vechi necriptat",
                    "2026-09-11T10:00:00+00:00",
                ),
            )
            connection.commit()
        finally:
            connection.close()

        self.database.initialize_database()
        connection = self.database.open_database()

        try:
            stored = connection.execute(
                "SELECT content FROM private_messages"
            ).fetchone()["content"]
            schema = connection.execute(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = 'private_messages'
                """
            ).fetchone()["sql"]
        finally:
            connection.close()

        self.assertTrue(
            stored.startswith("aes256ctr-hmacsha256:v1:")
        )
        self.assertNotIn("length(content)", schema)
        _contact, messages = self.database.get_private_conversation(
            self.users["bob"]["id"],
            self.users["alice"]["id"],
        )
        self.assertEqual(
            messages[0]["content"],
            "mesaj vechi necriptat",
        )

    def test_modified_ciphertext_is_rejected(self):
        encrypted = self.message_crypto.encrypt_message_content(
            "mesaj autentic"
        )
        prefix = self.message_crypto.TOKEN_PREFIX
        position = len(prefix) + 12
        replacement = "A" if encrypted[position] != "A" else "B"
        modified = (
            encrypted[:position]
            + replacement
            + encrypted[position + 1:]
        )

        with self.assertRaises(
            self.message_crypto.MessageDecryptionError
        ):
            self.message_crypto.decrypt_message_content(modified)

    def test_maximum_length_message_can_be_encrypted(self):
        self.assertEqual(self.login("alice").status_code, 200)

        response = self.send_to("bob", "ă" * 2000)

        self.assertEqual(response.status_code, 201)
        connection = self.database.open_database()

        try:
            stored_length = connection.execute(
                "SELECT length(content) AS size FROM private_messages"
            ).fetchone()["size"]
        finally:
            connection.close()

        self.assertGreater(stored_length, 2000)

    def test_backup_contains_message_encryption_key(self):
        self.assertEqual(self.login("alice").status_code, 200)
        self.send_to("bob", "Mesaj păstrat în backup")

        archive_path = self.backup.create_backup(keep=1)

        with tarfile.open(archive_path, "r:gz") as archive:
            names = set(archive.getnames())

        self.assertIn("cloud-in-buzunar.sqlite3", names)
        self.assertIn("message-encryption-key", names)

    def test_recipient_sees_unread_then_read_message(self):
        self.assertEqual(self.login("alice").status_code, 200)
        response = self.send_to("bob", "Ai primit mesajul?")
        message_id = response.get_json()["message"]["id"]
        self.client.post("/api/auth/logout")
        self.assertEqual(self.login("bob").status_code, 200)

        contacts = self.client.get(
            "/api/messages/contacts"
        ).get_json()["contacts"]
        alice = next(
            contact
            for contact in contacts
            if contact["username"] == "alice"
        )
        self.assertEqual(alice["unread_count"], 1)
        self.assertEqual(alice["last_message"], "Ai primit mesajul?")

        response = self.client.get(
            "/api/messages/conversations/"
            f"{self.users['alice']['id']}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.get_json()["messages"][0]["id"],
            message_id,
        )

        contacts = self.client.get(
            "/api/messages/contacts"
        ).get_json()["contacts"]
        alice = next(
            contact
            for contact in contacts
            if contact["username"] == "alice"
        )
        self.assertEqual(alice["unread_count"], 0)

    def test_conversation_after_id_returns_only_new_messages(self):
        self.assertEqual(self.login("alice").status_code, 200)
        first = self.send_to("bob", "Primul").get_json()["message"]
        second = self.send_to("bob", "Al doilea").get_json()["message"]

        response = self.client.get(
            "/api/messages/conversations/"
            f"{self.users['bob']['id']}?after_id={first['id']}"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [message["id"] for message in response.get_json()["messages"]],
            [second["id"]],
        )

    def test_cannot_message_self_or_inactive_user(self):
        self.assertEqual(self.login("alice").status_code, 200)

        self_message = self.send_to("alice", "Salut")
        inactive_message = self.send_to("inactive", "Salut")

        self.assertEqual(self_message.status_code, 400)
        self.assertEqual(inactive_message.status_code, 404)

    def test_message_length_is_limited(self):
        self.assertEqual(self.login("alice").status_code, 200)

        response = self.send_to("bob", "a" * 2001)

        self.assertEqual(response.status_code, 400)

    def test_message_html_is_returned_as_plain_content(self):
        self.assertEqual(self.login("alice").status_code, 200)
        content = '<script>alert("test")</script>'

        response = self.send_to("admin", content)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            response.get_json()["message"]["content"],
            content,
        )


if __name__ == "__main__":
    unittest.main()
