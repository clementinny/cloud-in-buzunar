# Security policy

## Reporting a vulnerability

Please do not publish credentials, private URLs or an exploitable security issue
in a public GitHub issue. Instead, use GitHub's private vulnerability reporting
feature when it is available for this repository.

Include the affected component, reproduction steps, expected impact and a
suggested mitigation if you have one. Reports about the latest release receive
priority.

## Scope and deployment

CloudInBuzunar is a personal home-server project, not a hardened public-cloud
service. Keep administrator, monitoring and Vaultwarden endpoints behind HTTPS
and preferably a trusted LAN or private VPN. Never commit the data directory,
generated certificates, databases, model files or secrets.
