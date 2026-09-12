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
            "--additional-host",
            "100.79.176.74",
            "--mode",
            "internal",
            "--no-autostart",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        caddyfile = (self.root / "data" / "caddy" / "Caddyfile").read_text(
            encoding="utf-8"
        )
        self.assertIn("https://phone.home.arpa:8443", caddyfile)
        self.assertIn("https://100.79.176.74:8443", caddyfile)
        self.assertIn("tls internal", caddyfile)
        self.assertIn("reverse_proxy http://127.0.0.1:8080", caddyfile)
        self.assertNotIn("caddy-access.log", caddyfile)
        self.assertFalse((self.root / "data" / "autostart.conf").exists())
        proxy_config = (self.root / "data" / "caddy" / "proxy.conf").read_text(
            encoding="utf-8"
        )
        self.assertIn("HTTPS_ADDITIONAL_HOSTS=100.79.176.74", proxy_config)

    def test_invalid_host_is_rejected_before_writing_configuration(self):
        result = self.run_configure("--host", "../../outside")

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "data" / "caddy" / "Caddyfile").exists())

    def test_invalid_additional_host_is_rejected(self):
        result = self.run_configure(
            "--host", "phone.home.arpa", "--additional-host", "bad host"
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / "data" / "caddy" / "Caddyfile").exists())

    def test_gunicorn_access_log_does_not_store_share_tokens(self):
        manager = (PROJECT_DIR / "scripts" / "cloud-services.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--access-logformat '%(h)s %(s)s %(L)s'", manager)
        self.assertNotIn("--access-logformat '%(r)s", manager)

    def test_https_health_check_uses_configured_listener_directly(self):
        manager = (PROJECT_DIR / "scripts" / "cloud-https.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("--noproxy '*'", manager)
        self.assertNotIn("--connect-to", manager)
        self.assertNotIn('--resolve "$HTTPS_HOST:$HTTPS_PORT:127.0.0.1"', manager)
        status_block = manager.split("status_proxy()", 1)[1].split(
            'case "${1:-}"', 1
        )[0]
        self.assertLess(
            status_block.index("if proxy_responds"),
            status_block.index('if process_id="$(running_pid)"'),
        )
        start_block = manager.split("start_proxy()", 1)[1].split(
            "stop_proxy()", 1
        )[0]
        self.assertIn(
            "Caddy rulează (PID %s), dar HTTPS nu răspunde; se repornește.",
            start_block,
        )
        self.assertIn("stop_proxy", start_block)


if __name__ == "__main__":
    unittest.main()
