#!/data/data/com.termux/files/usr/bin/bash

set -eu

PROJECT_DIR="${CLOUD_PROJECT_DIR:-$HOME/projects/cloud-in-buzunar}"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
BASE_DIR="$DATA_DIR/vaultwarden"
OCI_DIR="$BASE_DIR/oci"
BUNDLE_DIR="$BASE_DIR/bundle"
CONFIG_FILE="$BASE_DIR/vaultwarden.env"
AUTOSTART_CONFIG="$DATA_DIR/autostart.conf"
CADDY_DIR="$DATA_DIR/caddy"
CADDYFILE="$CADDY_DIR/Caddyfile"
SITES_DIR="$CADDY_DIR/sites"
SITE_FILE="$SITES_DIR/vaultwarden.caddy"
PROXY_CONFIG="$CADDY_DIR/proxy.conf"

VAULTWARDEN_VERSION="1.37.2"
VAULTWARDEN_ARM64_DIGEST="sha256:094b5689ed81549bd293418395c7cf495ae9d960fc2d4928cef2083ef913d912"
DOMAIN_HOST=""
ADDITIONAL_HOSTS=()
HTTPS_PORT=9443
UPSTREAM_PORT=8222
START_AFTER=false


usage() {
    cat <<'EOF'
Instalează Vaultwarden oficial ARM64 într-un mediu proot izolat pentru Termux.

Utilizare:
  scripts/install-vaultwarden.sh --host NUME [opțiuni]

Opțiuni:
  --host NUME             Adresa canonică (recomandat IP-ul Tailscale stabil)
  --additional-host NUME  Adresă suplimentară LAN; poate fi repetată
  --https-port PORT       Portul HTTPS extern (implicit 9443)
  --upstream-port PORT    Portul local Vaultwarden (implicit 8222)
  --start                 Pornește Vaultwarden și reîncarcă Caddy
  -h, --help              Afișează ajutorul

Înregistrarea este închisă implicit. Pentru primul cont:
  scripts/cloud-vaultwarden.sh signup-open
  # creează imediat contul din browser
  scripts/cloud-vaultwarden.sh signup-close
EOF
}


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


validate_host() {
    case "$1" in
        *[!A-Za-z0-9._-]*|.*|*..*|-*|*-|_*|'')
            die "numele gazdei conține caractere nepermise: $1"
            ;;
    esac
}


validate_port() {
    case "$1" in
        ''|*[!0-9]*) die "port invalid: $1" ;;
    esac
    [ "$1" -ge 1024 ] && [ "$1" -le 65535 ] \
        || die "portul trebuie să fie între 1024 și 65535."
}


while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            [ "$#" -ge 2 ] || die "--host necesită o valoare."
            DOMAIN_HOST="$2"
            shift 2
            ;;
        --additional-host)
            [ "$#" -ge 2 ] || die "--additional-host necesită o valoare."
            ADDITIONAL_HOSTS+=("$2")
            shift 2
            ;;
        --https-port)
            [ "$#" -ge 2 ] || die "--https-port necesită o valoare."
            HTTPS_PORT="$2"
            shift 2
            ;;
        --upstream-port)
            [ "$#" -ge 2 ] || die "--upstream-port necesită o valoare."
            UPSTREAM_PORT="$2"
            shift 2
            ;;
        --start)
            START_AFTER=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *) die "opțiune necunoscută: $1" ;;
    esac
done

[ -n "$DOMAIN_HOST" ] || die "lipsește --host."
validate_host "$DOMAIN_HOST"
for host in "${ADDITIONAL_HOSTS[@]}"; do
    validate_host "$host"
done
validate_port "$HTTPS_PORT"
validate_port "$UPSTREAM_PORT"
[ "$HTTPS_PORT" != "$UPSTREAM_PORT" ] || die "porturile HTTPS și upstream trebuie să fie diferite."
[ "$(uname -m)" = aarch64 ] || die "instalatorul este pregătit numai pentru ARM64."

command -v proot-distro >/dev/null 2>&1 \
    || die "proot-distro lipsește. Rulează: pkg install proot-distro"
command -v caddy >/dev/null 2>&1 \
    || die "Caddy lipsește. Rulează: pkg install caddy"
[ -r "$CADDYFILE" ] || die "Configurează mai întâi HTTPS-ul principal."

DEBIAN_ROOT="$PREFIX/var/lib/proot-distro/containers/debian/rootfs"
[ -d "$DEBIAN_ROOT" ] \
    || die "Debian proot lipsește. Rulează: proot-distro install debian"

mkdir -p "$BASE_DIR" "$OCI_DIR" "$BASE_DIR/data" "$SITES_DIR" "$DATA_DIR/runtime" "$DATA_DIR/logs"
chmod 700 "$BASE_DIR" "$BASE_DIR/data" "$SITES_DIR" "$DATA_DIR/runtime"

if ! proot-distro login debian -- bash -lc \
    'command -v skopeo >/dev/null && command -v umoci >/dev/null'; then
    printf 'Se instalează skopeo și umoci în Debian...\n'
    proot-distro login debian -- bash -lc \
        'apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends skopeo umoci ca-certificates'
fi

if [ ! -x "$BUNDLE_DIR/rootfs/vaultwarden" ]; then
    [ ! -e "$BUNDLE_DIR" ] \
        || die "$BUNDLE_DIR există, dar este incomplet; mută-l pentru diagnostic și reîncearcă."
    printf 'Se descarcă Vaultwarden %s ARM64 din registry-ul oficial...\n' "$VAULTWARDEN_VERSION"
    proot-distro login debian \
        --bind "$BASE_DIR:/mnt/vaultwarden" \
        -- bash -lc \
        "skopeo copy --override-os linux --override-arch arm64 docker://docker.io/vaultwarden/server@$VAULTWARDEN_ARM64_DIGEST oci:/mnt/vaultwarden/oci:$VAULTWARDEN_VERSION && umoci unpack --rootless --image /mnt/vaultwarden/oci:$VAULTWARDEN_VERSION /mnt/vaultwarden/bundle"
fi

printf '%s\n' "$VAULTWARDEN_VERSION" > "$BASE_DIR/version"
chmod 600 "$BASE_DIR/version"

if [ ! -f "$CONFIG_FILE" ]; then
    {
        printf 'VAULTWARDEN_DOMAIN=%q\n' "https://$DOMAIN_HOST:$HTTPS_PORT"
        printf 'VAULTWARDEN_ADDRESS=127.0.0.1\n'
        printf 'VAULTWARDEN_PORT=%q\n' "$UPSTREAM_PORT"
        printf 'VAULTWARDEN_SIGNUPS_ALLOWED=false\n'
        printf 'VAULTWARDEN_ADMIN_TOKEN=\n'
        printf 'VAULTWARDEN_BACKUP_KEEP=7\n'
    } > "$CONFIG_FILE"
    chmod 600 "$CONFIG_FILE"
fi

{
    printf 'https://%s:%s' "$DOMAIN_HOST" "$HTTPS_PORT"
    for host in "${ADDITIONAL_HOSTS[@]}"; do
        printf ', https://%s:%s' "$host" "$HTTPS_PORT"
    done
    printf ' {\n'
    printf '    tls internal\n'
    printf '    encode zstd gzip\n'
    printf '    reverse_proxy 127.0.0.1:%s\n' "$UPSTREAM_PORT"
    printf '    header {\n'
    printf '        X-Content-Type-Options "nosniff"\n'
    printf '        Referrer-Policy "same-origin"\n'
    printf '        X-Frame-Options "SAMEORIGIN"\n'
    printf '        -Server\n'
    printf '    }\n'
    printf '}\n'
} > "$SITE_FILE"
chmod 600 "$SITE_FILE"

IMPORT_LINE="import $SITES_DIR/*.caddy"
if ! grep -Fqx "$IMPORT_LINE" "$CADDYFILE"; then
    printf '\n%s\n' "$IMPORT_LINE" >> "$CADDYFILE"
fi

XDG_DATA_HOME="$CADDY_DIR/data" \
XDG_CONFIG_HOME="$CADDY_DIR/config" \
    caddy fmt --overwrite "$SITE_FILE" >/dev/null
XDG_DATA_HOME="$CADDY_DIR/data" \
XDG_CONFIG_HOME="$CADDY_DIR/config" \
    caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null

if [ -f "$AUTOSTART_CONFIG" ] && grep -q '^START_VAULTWARDEN=' "$AUTOSTART_CONFIG"; then
    sed -i 's/^START_VAULTWARDEN=.*/START_VAULTWARDEN=true/' "$AUTOSTART_CONFIG"
else
    printf 'START_VAULTWARDEN=true\n' >> "$AUTOSTART_CONFIG"
fi
chmod 600 "$AUTOSTART_CONFIG"

printf 'Vaultwarden instalat: https://%s:%s\n' "$DOMAIN_HOST" "$HTTPS_PORT"
printf 'Înregistrarea conturilor este închisă implicit.\n'

if [ "$START_AFTER" = true ]; then
    "$PROJECT_DIR/scripts/cloud-vaultwarden.sh" start
    "$PROJECT_DIR/scripts/cloud-https.sh" restart
fi
