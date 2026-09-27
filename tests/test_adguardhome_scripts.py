import unittest
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
INSTALLER = PROJECT_DIR / "scripts" / "install-adguardhome.sh"
MANAGER = PROJECT_DIR / "scripts" / "cloud-adguardhome.sh"
SERVICES = PROJECT_DIR / "scripts" / "cloud-services.sh"


class AdGuardHomeScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.installer = INSTALLER.read_text(encoding="utf-8")
        cls.manager = MANAGER.read_text(encoding="utf-8")
        cls.services = SERVICES.read_text(encoding="utf-8")

    def test_installer_pins_official_arm64_release_and_checksum(self):
        self.assertIn('ADGUARD_VERSION="v0.107.79"', self.installer)
        self.assertIn("AdguardTeam/AdGuardHome/releases/download", self.installer)
        self.assertIn(
            'ADGUARD_SHA256="3f7893c18e8aaadc456d0452839190561c306ca95175a2254958be80a769c1ae"',
            self.installer,
        )
        self.assertIn("sha256sum --check --status", self.installer)
        self.assertIn("--proto '=https'", self.installer)

    def test_installer_accepts_both_official_archive_layouts(self):
        self.assertIn(
            '"$extracted_dir/AdGuardHome/AdGuardHome"',
            self.installer,
        )
        self.assertIn(
            '"$extracted_dir/AdGuardHome"',
            self.installer,
        )
        self.assertIn(
            '"$release_dir/AdGuardHome.sig"',
            self.installer,
        )

    def test_dns_process_is_unprivileged_after_root_bootstrap(self):
        self.assertIn('DNS_PORT=1053', self.installer)
        self.assertIn('ADGUARD_DNS_PORT=1053', self.manager)
        self.assertNotIn('DNS_PORT=5353', self.installer)
        start_section = self.manager.split("start_service()", 1)[1].split(
            "stop_process()",
            1,
        )[0]
        self.assertIn('nohup "$BINARY"', start_section)
        self.assertNotIn("su -c", start_section)
        self.assertIn("start_bootstrap()", self.manager)
        self.assertIn("finalize_setup()", self.manager)
        self.assertIn('su -c "$root_script"', self.manager)
        self.assertIn('chown -R %q:%q %q', self.manager)
        self.assertIn('finalize) finalize_setup', self.manager)
        self.assertIn('disable_android_arp_source', self.manager)
        self.assertIn("arp:[[:space:]]*true", self.manager)
        self.assertIn('CA_CERT_FILE=', self.manager)
        self.assertIn('SSL_CERT_FILE="$CA_CERT_FILE" nohup', self.manager)
        self.assertIn("--dport 53", self.manager)
        self.assertIn("--to-ports $ADGUARD_DNS_PORT", self.manager)
        self.assertIn("for protocol in udp tcp", self.manager)

    def test_service_supervisor_starts_and_monitors_adguardhome(self):
        self.assertIn("START_ADGUARDHOME=false", self.services)
        self.assertIn("start_adguardhome || true", self.services)
        self.assertIn("adguardhome_is_healthy", self.services)
        self.assertIn("restart_adguardhome || true", self.services)
        self.assertIn("adguardhome-start)", self.services)
        self.assertIn("adguardhome-stop)", self.services)


if __name__ == "__main__":
    unittest.main()
