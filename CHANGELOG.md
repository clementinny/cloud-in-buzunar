# Changelog
+All notable changes to CloudInBuzunar are documented here.

## [1.0.11] - 2026-09-14

First public stable milestone of the complete phone-server stack.

### Added

- Multi-user personal file vault, media library and private messaging
- aria2 and Transmission download controls
- Local AI profiles powered by `llama.cpp`
- Native Android companion with server alerts, motion detection and opt-in
  camera/audio monitoring
- Rolling audio/video recordings with likely-speech markers
- Root-aware CPU, GPU, process, battery and temperature monitoring
- Thermal protection, service watchdog and automatic backups
- HTTPS reverse proxy, portable migration archives and expiring file links
- Optional Vaultwarden service
- Automated Python, JavaScript, shell and Android checks

### Language

- The web interface and Android companion currently use Romanian.
- English localization is planned for a future update.

### Notes

- The Android application is distributed as a sideloaded APK and is not
  published through Google Play.
- Root-only telemetry and charging controls depend on the phone kernel and
  require validation on the target device.
- Administrative services should remain behind HTTPS and a trusted LAN or
  private VPN.

[1.0.11]: https://github.com/clementinny/cloud-in-buzunar/releases/tag/v1.0.11
