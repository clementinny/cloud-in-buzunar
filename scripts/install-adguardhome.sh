#!/data/data/com.termux/files/usr/bin/bash

set -eu

PROJECT_DIR="${CLOUD_PROJECT_DIR:-$HOME/projects/cloud-in-buzunar}"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
BASE_DIR="$DATA_DIR/adguardhome"
APP_DIR="$BASE_DIR/app"
WORK_DIR="$BASE_DIR/work"
CONFIG_DIR="$BASE_DIR/config"
SETTINGS_FILE="$BASE_DIR/adguardhome.env"
AUTOSTART_CONFIG="$DATA_DIR/autostart.conf"
MANAGER="$PROJECT_DIR/scripts/cloud-adguardhome.sh"

ADGUARD_VERSION="v0.107.79"
ADGUARD_ARCHIVE="AdGuardHome_linux_arm64.tar.gz"
ADGUARD_URL="https://github.com/AdguardTeam/AdGuardHome/releases/download/$ADGUARD_VERSION/$ADGUARD_ARCHIVE"
ADGUARD_SHA256="3f7893c18e8aaadc456d0452839190561c306ca95175a2254958be80a769c1ae"

ADMIN_PORT=3000
DNS_PORT=1053
LAN_INTERFACE="wlan0"
START_AFTER=false


usage() {
    cat <<'EOF'
Instalează versiunea oficială ARM64 AdGuard Home pentru CloudInBuzunar.

Utilizare:
  scripts/install-adguardhome.sh [opțiuni]

Opțiuni:
  --admin-port PORT      Panoul web local (implicit 3000)
  --dns-port PORT        Portul DNS intern neprivilegiat (implicit 1053)
  --interface NUME       Interfața LAN Android (implicit wlan0)
  --start                Pornește serviciul după instalare
  -h, --help             Afișează ajutorul

Root este folosit pentru regulile iptables și temporar la prima configurare,
conform cerinței AdGuard Home. După finalizare, procesul rulează cu utilizatorul
Termux, fără privilegii root.
EOF
}


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


validate_port() {
    case "$1" in
        ''|*[!0-9]*) die "port invalid: $1" ;;
    esac
    [ "$1" -ge 1024 ] && [ "$1" -le 65535 ] \
        || die "portul intern trebuie să fie între 1024 și 65535."
}


while [ "$#" -gt 0 ]; do
    case "$1" in
        --admin-port)
            [ "$#" -ge 2 ] || die "--admin-port necesită o valoare."
            ADMIN_PORT="$2"
            shift 2
            ;;
        --dns-port)
            [ "$#" -ge 2 ] || die "--dns-port necesită o valoare."
            DNS_PORT="$2"
            shift 2
            ;;
        --interface)
            [ "$#" -ge 2 ] || die "--interface necesită o valoare."
            LAN_INTERFACE="$2"
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

validate_port "$ADMIN_PORT"
validate_port "$DNS_PORT"
[ "$ADMIN_PORT" != "$DNS_PORT" ] \
    || die "porturile web și DNS trebuie să fie diferite."
case "$LAN_INTERFACE" in
    ''|*[!A-Za-z0-9_.:-]*) die "interfață LAN invalidă: $LAN_INTERFACE" ;;
esac
[ "$(uname -m)" = aarch64 ] \
    || die "instalatorul este pregătit numai pentru ARM64."

for command_name in curl tar sha256sum su; do
    command -v "$command_name" >/dev/null 2>&1 \
        || die "$command_name lipsește."
done
[ -x "$MANAGER" ] \
    || die "Managerul AdGuard Home lipsește sau nu este executabil."

mkdir -p "$BASE_DIR" "$APP_DIR" "$WORK_DIR" "$CONFIG_DIR" \
    "$DATA_DIR/runtime" "$DATA_DIR/logs"
chmod 700 "$BASE_DIR" "$APP_DIR" "$WORK_DIR" "$CONFIG_DIR" "$DATA_DIR/runtime"

current_version=""
if [ -x "$APP_DIR/AdGuardHome" ]; then
    current_version="$($APP_DIR/AdGuardHome --version 2>/dev/null || true)"
fi

case "$current_version" in
    *"$ADGUARD_VERSION"*)
        printf 'AdGuard Home %s este deja instalat.\n' "$ADGUARD_VERSION"
        ;;
    *)
        temporary_dir="$(mktemp -d "$BASE_DIR/.install.XXXXXX")"
        trap 'rm -rf "$temporary_dir"' EXIT INT TERM
        archive_path="$temporary_dir/$ADGUARD_ARCHIVE"

        printf 'Se descarcă AdGuard Home %s ARM64 din release-ul oficial...\n' \
            "$ADGUARD_VERSION"
        curl --fail --location --proto '=https' --tlsv1.2 \
            --output "$archive_path" "$ADGUARD_URL"
        printf '%s  %s\n' "$ADGUARD_SHA256" "$archive_path" \
            | sha256sum --check --status \
            || die "Checksumul arhivei AdGuard Home nu corespunde."

        extracted_dir="$temporary_dir/extracted"
        mkdir -p "$extracted_dir"
        tar -xzf "$archive_path" -C "$extracted_dir"

        if [ -x "$extracted_dir/AdGuardHome/AdGuardHome" ]; then
            release_dir="$extracted_dir/AdGuardHome"
        elif [ -x "$extracted_dir/AdGuardHome" ]; then
            release_dir="$extracted_dir"
        else
            die "Arhiva verificată nu conține executabilul AdGuardHome."
        fi

        [ -f "$release_dir/AdGuardHome.sig" ] \
            || die "Semnătura executabilului lipsește din arhivă."
        [ -f "$release_dir/LICENSE.txt" ] \
            || die "Licența AdGuard Home lipsește din arhivă."
        install -m 700 \
            "$release_dir/AdGuardHome" \
            "$APP_DIR/AdGuardHome.new"
        mv "$APP_DIR/AdGuardHome.new" "$APP_DIR/AdGuardHome"
        install -m 600 \
            "$release_dir/AdGuardHome.sig" \
            "$APP_DIR/AdGuardHome.sig"
        install -m 600 \
            "$release_dir/LICENSE.txt" \
            "$APP_DIR/LICENSE.txt"
        printf '%s\n' "$ADGUARD_VERSION" > "$BASE_DIR/version"
        chmod 600 "$BASE_DIR/version"
        rm -rf "$temporary_dir"
        trap - EXIT INT TERM
        ;;
esac

if [ ! -f "$SETTINGS_FILE" ]; then
    {
        printf 'ADGUARD_BIND_HOST=0.0.0.0\n'
        printf 'ADGUARD_ADMIN_PORT=%q\n' "$ADMIN_PORT"
        printf 'ADGUARD_DNS_PORT=%q\n' "$DNS_PORT"
        printf 'ADGUARD_LAN_INTERFACE=%q\n' "$LAN_INTERFACE"
    } > "$SETTINGS_FILE"
    chmod 600 "$SETTINGS_FILE"
fi

if [ -f "$AUTOSTART_CONFIG" ] \
    && grep -q '^START_ADGUARDHOME=' "$AUTOSTART_CONFIG"; then
    sed -i 's/^START_ADGUARDHOME=.*/START_ADGUARDHOME=true/' "$AUTOSTART_CONFIG"
else
    printf 'START_ADGUARDHOME=true\n' >> "$AUTOSTART_CONFIG"
fi
chmod 600 "$AUTOSTART_CONFIG"

printf '\nAdGuard Home %s instalat.\n' "$ADGUARD_VERSION"
printf 'Panou inițial: http://ADRESA_TELEFONULUI:%s\n' "$ADMIN_PORT"
printf 'DNS intern: %s; clienții folosesc portul standard 53 prin redirecționare root.\n' "$DNS_PORT"

if [ "$START_AFTER" = true ]; then
    "$MANAGER" start
fi
