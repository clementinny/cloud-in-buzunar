#!/data/data/com.termux/files/usr/bin/bash

set -eu

DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
BASE_DIR="$DATA_DIR/adguardhome"
APP_DIR="$BASE_DIR/app"
WORK_DIR="$BASE_DIR/work"
CONFIG_DIR="$BASE_DIR/config"
CONFIG_FILE="$CONFIG_DIR/AdGuardHome.yaml"
SETTINGS_FILE="$BASE_DIR/adguardhome.env"
BINARY="$APP_DIR/AdGuardHome"
PID_FILE="$DATA_DIR/runtime/adguardhome.pid"
LOG_FILE="$DATA_DIR/logs/adguardhome.log"

ADGUARD_BIND_HOST="0.0.0.0"
ADGUARD_ADMIN_PORT=3000
ADGUARD_DNS_PORT=5353
ADGUARD_LAN_INTERFACE="wlan0"


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


load_config() {
    [ -r "$SETTINGS_FILE" ] \
        || die "AdGuard Home nu este configurat. Rulează scripts/install-adguardhome.sh"
    # Fișier local 0600, creat de instalator.
    # shellcheck source=/dev/null
    source "$SETTINGS_FILE"

    for port in "$ADGUARD_ADMIN_PORT" "$ADGUARD_DNS_PORT"; do
        case "$port" in
            ''|*[!0-9]*) die "Un port AdGuard Home este invalid." ;;
        esac
        [ "$port" -ge 1024 ] && [ "$port" -le 65535 ] \
            || die "Porturile interne trebuie să fie între 1024 și 65535."
    done
    [ "$ADGUARD_ADMIN_PORT" != "$ADGUARD_DNS_PORT" ] \
        || die "Porturile web și DNS trebuie să fie diferite."
    case "$ADGUARD_LAN_INTERFACE" in
        ''|*[!A-Za-z0-9_.:-]*) die "Interfața LAN este invalidă." ;;
    esac
}


running_pid() {
    local process_id
    local command_line
    process_id="$(cat "$PID_FILE" 2>/dev/null || true)"

    case "$process_id" in
        ''|*[!0-9]*) return 1 ;;
    esac

    kill -0 "$process_id" 2>/dev/null || return 1
    command_line="$(tr '\0' ' ' < "/proc/$process_id/cmdline" 2>/dev/null || true)"
    case "$command_line" in
        *"$BINARY"*)
            printf '%s\n' "$process_id"
            return 0
            ;;
    esac
    return 1
}


responds() {
    curl \
        --silent \
        --show-error \
        --max-time 4 \
        --output /dev/null \
        "http://127.0.0.1:$ADGUARD_ADMIN_PORT/" \
        >/dev/null 2>&1
}


ensure_dns_redirect() {
    command -v su >/dev/null 2>&1 \
        || die "Comanda su lipsește; redirecționarea DNS necesită root."

    local root_script
    root_script="
set -e
for protocol in udp tcp; do
    if ! iptables -t nat -C PREROUTING -i $ADGUARD_LAN_INTERFACE -p \"\$protocol\" --dport 53 -j REDIRECT --to-ports $ADGUARD_DNS_PORT >/dev/null 2>&1; then
        iptables -t nat -I PREROUTING -i $ADGUARD_LAN_INTERFACE -p \"\$protocol\" --dport 53 -j REDIRECT --to-ports $ADGUARD_DNS_PORT
    fi
done
"
    su -c "$root_script" >/dev/null \
        || die "Regulile DNS nu au putut fi adăugate."
}


remove_dns_redirect() {
    command -v su >/dev/null 2>&1 || return 0

    local root_script
    root_script="
for protocol in udp tcp; do
    while iptables -t nat -C PREROUTING -i $ADGUARD_LAN_INTERFACE -p \"\$protocol\" --dport 53 -j REDIRECT --to-ports $ADGUARD_DNS_PORT >/dev/null 2>&1; do
        iptables -t nat -D PREROUTING -i $ADGUARD_LAN_INTERFACE -p \"\$protocol\" --dport 53 -j REDIRECT --to-ports $ADGUARD_DNS_PORT || break
    done
done
"
    su -c "$root_script" >/dev/null 2>&1 || true
}


start_service() {
    load_config
    [ -x "$BINARY" ] \
        || die "Executabilul AdGuard Home lipsește. Rulează din nou instalatorul."

    mkdir -p "$WORK_DIR" "$CONFIG_DIR" "$DATA_DIR/runtime" "$DATA_DIR/logs"
    chmod 700 "$BASE_DIR" "$WORK_DIR" "$CONFIG_DIR" "$DATA_DIR/runtime"

    if responds; then
        ensure_dns_redirect
        printf 'AdGuard Home răspunde deja pe portul web %s.\n' "$ADGUARD_ADMIN_PORT"
        return 0
    fi

    local process_id
    if process_id="$(running_pid)"; then
        printf 'Procesul AdGuard Home %s nu răspunde; se repornește.\n' "$process_id"
        stop_process
    fi

    ensure_dns_redirect
    rm -f "$PID_FILE"

    nohup "$BINARY" \
        --config "$CONFIG_FILE" \
        --work-dir "$WORK_DIR" \
        --web-addr "$ADGUARD_BIND_HOST:$ADGUARD_ADMIN_PORT" \
        >> "$LOG_FILE" 2>&1 &
    printf '%s\n' "$!" > "$PID_FILE"
    chmod 600 "$PID_FILE"

    for _attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if responds; then
            printf 'AdGuard Home pornit. Panou: http://ADRESA_TELEFONULUI:%s\n' \
                "$ADGUARD_ADMIN_PORT"
            return 0
        fi
        sleep 1
    done

    tail -n 30 "$LOG_FILE" >&2 || true
    remove_dns_redirect || true
    die "AdGuard Home nu a răspuns în timpul alocat."
}


stop_process() {
    local process_id
    process_id="$(running_pid || true)"

    if [ -z "$process_id" ]; then
        rm -f "$PID_FILE"
        return 0
    fi

    kill "$process_id" 2>/dev/null || true
    for _attempt in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "$process_id" 2>/dev/null; then
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done
    die "AdGuard Home nu s-a oprit în timpul alocat (PID $process_id)."
}


stop_service() {
    load_config
    stop_process
    remove_dns_redirect
    printf 'AdGuard Home a fost oprit, iar redirecționarea DNS a fost eliminată.\n'
}


status_service() {
    load_config
    local process_id
    if responds; then
        process_id="$(running_pid || true)"
        printf 'AdGuard Home online: web %s, DNS intern %s' \
            "$ADGUARD_ADMIN_PORT" "$ADGUARD_DNS_PORT"
        [ -n "$process_id" ] && printf ' (PID %s)' "$process_id"
        printf '\n'
        return 0
    fi
    printf 'AdGuard Home oprit.\n'
    return 1
}


firewall_status() {
    load_config
    local root_script
    root_script="
missing=false
for protocol in udp tcp; do
    if iptables -t nat -C PREROUTING -i $ADGUARD_LAN_INTERFACE -p \"\$protocol\" --dport 53 -j REDIRECT --to-ports $ADGUARD_DNS_PORT >/dev/null 2>&1; then
        echo \"Redirecționare DNS \$protocol 53 -> $ADGUARD_DNS_PORT: activă\"
    else
        echo \"Redirecționare DNS \$protocol 53 -> $ADGUARD_DNS_PORT: lipsește\"
        missing=true
    fi
done
[ \"\$missing\" = false ]
"
    su -c "$root_script"
}


case "${1:-}" in
    start) start_service ;;
    stop) stop_service ;;
    restart)
        stop_service || true
        start_service
        ;;
    status) status_service ;;
    firewall-enable)
        load_config
        ensure_dns_redirect
        ;;
    firewall-disable)
        load_config
        remove_dns_redirect
        ;;
    firewall-status) firewall_status ;;
    *)
        printf 'Utilizare: %s {start|stop|restart|status|firewall-enable|firewall-disable|firewall-status}\n' "$0" >&2
        exit 1
        ;;
esac
