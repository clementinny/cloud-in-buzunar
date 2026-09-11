import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIGURE_SCRIPT = PROJECT_DIR / "scripts" / "configure-https.sh"


@unittest.skipUnless(os.name == "posix", "HTTPS script test runs in Linux CI")
class HttpsScriptTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.fake_bin = self.root / "bin"
        self.fake_bin.mkdir()
        fake_caddy = self.fake_bin / "caddy"
        fake_caddy.write_text(
            "#!/usr/bin/env bash\n"
            "case \"${1:-}\" in\n"
            "  fmt|validate) exit 0 ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        fake_caddy.chmod(0o700)
        self.environment = os.environ.copy()
        self.environment["HOME"] = str(self.root / "home")
        self.environment["CLOUD_DATA_DIR"] = str(self.root / "data")
        self.environment["PATH"] = (
            f"{self.fake_bin}{os.pathsep}{self.environment['PATH']}"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def run_configure(self, *arguments):
        return subprocess.run(
            ["bash", str(CONFIGURE_SCRIPT), *arguments],
            capture_output=True,
            check=False,
            env=self.environment,
            text=True,
            timeout=10,
        )

    def test_internal_https_configuration_is_private_and_validated(self):
        result = self.run_configure(
            "--host",
            "phone.home.arpa",
            "--mode",
            "internal",
            "--no-autostart",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        caddyfile = (self.root / "data" / "caddy" / "Caddyfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://phone.home.arpa:8443", caddyfile)
        self.assertIn("tls internal", caddyfile)
        self.assertIn("reverse_proxy http://127.0.0.1:8080", caddyfile)
        self.assertNotIn("caddy-access.log", caddyfile)
        self.assertFalse((self.root / "data" / "autostart.conf").exists())

    def test_invalid_host_is_rejected_before_writing_configuration(self):
        result = self.run_configure("--host", "../../outside")

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "data" / "caddy" / "Caddyfile").exists())

    def test_gunicorn_access_log_does_not_store_share_tokens(self):
        manager = (PROJECT_DIR / "scripts" / "cloud-services.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--access-logformat '%(h)s %(s)s %(L)s'", manager)
        self.assertNotIn("--access-logformat '%(r)s", manager)


if __name__ == "__main__":
    unittest.main()
