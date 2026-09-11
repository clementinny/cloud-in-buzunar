#!/data/data/com.termux/files/usr/bin/bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
CADDY_DIR="$DATA_DIR/caddy"
CADDYFILE="$CADDY_DIR/Caddyfile"
PROXY_CONFIG="$CADDY_DIR/proxy.conf"
AUTOSTART_CONFIG="$DATA_DIR/autostart.conf"
HOST_NAME=""
HTTPS_PORT=8443
UPSTREAM="127.0.0.1:8080"
TLS_MODE="internal"
CERT_FILE=""
KEY_FILE=""
START_AFTER=false
ENABLE_AUTOSTART=true


usage() {
    cat <<'EOF'
Configurează HTTPS pentru CloudInBuzunar prin Caddy.

Utilizare:
  scripts/configure-https.sh --host NUME [opțiuni]

Opțiuni:
  --host NUME             Nume DNS sau adresă IP folosită în browser (obligatoriu)
  --port PORT             Port HTTPS local (implicit: 8443)
  --upstream HOST:PORT    Serverul web intern (implicit: 127.0.0.1:8080)
  --mode MOD              internal, automatic sau certificate (implicit: internal)
  --cert FIȘIER           Certificat PEM pentru modul certificate
  --key FIȘIER            Cheie privată PEM pentru modul certificate
  --start                 Pornește proxy-ul după validare
  --no-autostart          Nu activează proxy-ul în watchdog/Termux:Boot
  -h, --help              Afișează acest ajutor

Moduri TLS:
  internal     Certificat emis local de Caddy. Bun pentru LAN/VPN; certificatul
               rădăcină trebuie instalat o singură dată pe dispozitivele client.
  automatic    Certificat public automat. Necesită domeniu public, DNS corect și
               TCP 443 din internet redirecționat la portul HTTPS ales.
  certificate  Folosește fișierele date prin --cert și --key (de exemplu un
               certificat obținut pentru numele privat/VPN).
EOF
}


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


absolute_file() {
    local file_path="$1"
    local file_dir
    local file_name

    file_dir="$(cd "$(dirname "$file_path")" && pwd)"
    file_name="$(basename "$file_path")"
    printf '%s/%s\n' "$file_dir" "$file_name"
}


while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            [ "$#" -ge 2 ] || die "--host necesită o valoare."
            HOST_NAME="$2"
            shift 2
            ;;
        --port)
            [ "$#" -ge 2 ] || die "--port necesită o valoare."
            HTTPS_PORT="$2"
            shift 2
            ;;
        --upstream)
            [ "$#" -ge 2 ] || die "--upstream necesită o valoare."
            UPSTREAM="$2"
            shift 2
            ;;
        --mode)
            [ "$#" -ge 2 ] || die "--mode necesită o valoare."
            TLS_MODE="$2"
            shift 2
            ;;
        --cert)
            [ "$#" -ge 2 ] || die "--cert necesită o valoare."
            CERT_FILE="$2"
            shift 2
            ;;
        --key)
            [ "$#" -ge 2 ] || die "--key necesită o valoare."
            KEY_FILE="$2"
            shift 2
            ;;
        --start)
            START_AFTER=true
            shift
            ;;
        --no-autostart)
            ENABLE_AUTOSTART=false
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "opțiune necunoscută: $1"
            ;;
    esac
done

[ -n "$HOST_NAME" ] || die "lipsește --host."

case "$HOST_NAME" in
    *[!A-Za-z0-9._-]*|.*|*..*|-*|*-|_*|'')
        die "numele gazdei conține caractere nepermise."
        ;;
esac

case "$HTTPS_PORT" in
    ''|*[!0-9]*) die "portul HTTPS trebuie să fie numeric." ;;
esac

[ "$HTTPS_PORT" -ge 1 ] && [ "$HTTPS_PORT" -le 65535 ] \
    || die "portul HTTPS trebuie să fie între 1 și 65535."

if ! [[ "$UPSTREAM" =~ ^[A-Za-z0-9._-]+:[0-9]{1,5}$ ]]; then
    die "upstream invalid; folosește forma HOST:PORT."
fi

UPSTREAM_PORT="${UPSTREAM##*:}"
[ "$UPSTREAM_PORT" -ge 1 ] && [ "$UPSTREAM_PORT" -le 65535 ] \
    || die "portul upstream trebuie să fie între 1 și 65535."

case "$TLS_MODE" in
    internal)
        TLS_DIRECTIVE='    tls internal'
        ;;
    automatic)
        TLS_DIRECTIVE=''
        ;;
    certificate)
        [ -r "$CERT_FILE" ] || die "certificatul nu poate fi citit."
        [ -r "$KEY_FILE" ] || die "cheia privată nu poate fi citită."
        CERT_FILE="$(absolute_file "$CERT_FILE")"
        KEY_FILE="$(absolute_file "$KEY_FILE")"
        case "$CERT_FILE$KEY_FILE" in
            *'"'*|*$'\n'*) die "calea certificatului nu este acceptată." ;;
        esac
        TLS_DIRECTIVE="    tls \"$CERT_FILE\" \"$KEY_FILE\""
        ;;
    *)
        die "--mode trebuie să fie internal, automatic sau certificate."
        ;;
esac

command -v caddy >/dev/null 2>&1 \
    || die "Caddy nu este instalat. Rulează: pkg install caddy"

mkdir -p "$CADDY_DIR" "$CADDY_DIR/data" "$CADDY_DIR/config" "$DATA_DIR/logs" "$DATA_DIR/runtime"
chmod 700 "$CADDY_DIR" "$CADDY_DIR/data" "$CADDY_DIR/config" "$DATA_DIR/runtime"

TEMP_CADDYFILE="$CADDYFILE.tmp.$$"
trap 'rm -f "$TEMP_CADDYFILE"' EXIT INT TERM

{
    printf '{\n'
    printf '    admin 127.0.0.1:2019\n'
    printf '    auto_https disable_redirects\n'
    printf '}\n\n'
    printf 'https://%s:%s {\n' "$HOST_NAME" "$HTTPS_PORT"
    [ -n "$TLS_DIRECTIVE" ] && printf '%s\n' "$TLS_DIRECTIVE"
    printf '    encode zstd gzip\n'
    printf '    reverse_proxy http://%s {\n' "$UPSTREAM"
    printf '        health_uri /api/health\n'
    printf '        health_interval 30s\n'
    printf '        health_timeout 5s\n'
    printf '    }\n'
    printf '    header {\n'
    printf '        X-Content-Type-Options "nosniff"\n'
    printf '        Referrer-Policy "same-origin"\n'
    printf '        X-Frame-Options "SAMEORIGIN"\n'
    printf '        -Server\n'
    printf '    }\n'
    printf '}\n'
} > "$TEMP_CADDYFILE"

XDG_DATA_HOME="$CADDY_DIR/data" \
XDG_CONFIG_HOME="$CADDY_DIR/config" \
    caddy fmt --overwrite "$TEMP_CADDYFILE" >/dev/null

XDG_DATA_HOME="$CADDY_DIR/data" \
XDG_CONFIG_HOME="$CADDY_DIR/config" \
    caddy validate --config "$TEMP_CADDYFILE" --adapter caddyfile >/dev/null

mv "$TEMP_CADDYFILE" "$CADDYFILE"
chmod 600 "$CADDYFILE"

{
    printf 'HTTPS_HOST=%q\n' "$HOST_NAME"
    printf 'HTTPS_PORT=%q\n' "$HTTPS_PORT"
    printf 'HTTPS_MODE=%q\n' "$TLS_MODE"
    printf 'HTTPS_UPSTREAM=%q\n' "$UPSTREAM"
} > "$PROXY_CONFIG"
chmod 600 "$PROXY_CONFIG"

if [ "$ENABLE_AUTOSTART" = true ]; then
    if [ -f "$AUTOSTART_CONFIG" ] \
        && grep -q '^START_HTTPS=' "$AUTOSTART_CONFIG"; then
        sed -i 's/^START_HTTPS=.*/START_HTTPS=true/' "$AUTOSTART_CONFIG"
    else
        printf 'START_HTTPS=true\n' >> "$AUTOSTART_CONFIG"
    fi
    chmod 600 "$AUTOSTART_CONFIG"
fi

printf 'HTTPS configurat: https://%s:%s\n' "$HOST_NAME" "$HTTPS_PORT"
printf 'Configurație Caddy: %s\n' "$CADDYFILE"
printf 'Pornire automată HTTPS: %s\n' "$ENABLE_AUTOSTART"

if [ "$TLS_MODE" = internal ]; then
    printf 'După prima pornire, certificatul CA pentru clienți va fi în:\n'
    printf '  %s/data/caddy/pki/authorities/local/root.crt\n' "$CADDY_DIR"
fi

if [ "$START_AFTER" = true ]; then
    exec bash "$PROJECT_DIR/scripts/cloud-https.sh" restart
fi
