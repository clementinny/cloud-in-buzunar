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
BOOTSTRAP_PID_FILE="$DATA_DIR/runtime/adguardhome-bootstrap.pid"
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
    su -c "$root_script" >/dev/null 2>&1 \
        || die "Procesul temporar AdGuard Home nu a putut fi oprit."
}


start_bootstrap() {
    if responds; then
        printf 'Configurarea inițială AdGuard Home este deja disponibilă pe portul %s.\n' \
            "$ADGUARD_ADMIN_PORT"
        return 0
    fi

    local nohup_binary
    local process_id
    local root_script
    nohup_binary="$(command -v nohup)"
    printf -v root_script \
        '%q %q --config %q --work-dir %q --web-addr %q >> %q 2>&1 & echo $!' \
        "$nohup_binary" \
        "$BINARY" \
        "$CONFIG_FILE" \
        "$WORK_DIR" \
        "$ADGUARD_BIND_HOST:$ADGUARD_ADMIN_PORT" \
        "$LOG_FILE"

    process_id="$(su -c "$root_script" | tail -n 1 | tr -d '\r')"
    case "$process_id" in
        ''|*[!0-9]*) die "Procesul temporar de configurare nu a putut fi pornit." ;;
    esac
    printf '%s\n' "$process_id" > "$BOOTSTRAP_PID_FILE"
    chmod 600 "$BOOTSTRAP_PID_FILE"

    for _attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        if responds; then
            printf 'Configurarea inițială AdGuard Home a pornit temporar cu root.\n'
            printf 'Deschide http://ADRESA_TELEFONULUI:%s și alege DNS port %s.\n' \
                "$ADGUARD_ADMIN_PORT" "$ADGUARD_DNS_PORT"
            printf 'După terminarea configurării rulează: %s finalize\n' "$0"
            return 0
        fi
        sleep 1
    done

    tail -n 30 "$LOG_FILE" >&2 || true
    die "Configurarea inițială AdGuard Home nu a răspuns în timpul alocat."
}


stop_bootstrap() {
    local process_id
    local root_script
    process_id="$(cat "$BOOTSTRAP_PID_FILE" 2>/dev/null || true)"
    case "$process_id" in
        ''|*[!0-9]*)
            rm -f "$BOOTSTRAP_PID_FILE"
            return 0
            ;;
    esac

    printf -v root_script \
        'kill %q >/dev/null 2>&1 || true; for attempt in 1 2 3 4 5 6 7 8 9 10; do kill -0 %q >/dev/null 2>&1 || exit 0; sleep 1; done; kill -9 %q >/dev/null 2>&1 || true' \
        "$process_id" "$process_id" "$process_id"
    su -c "$root_script" >/dev/null 2>&1 || true
    rm -f "$BOOTSTRAP_PID_FILE"
}


finalize_setup() {
    load_config
    [ -s "$CONFIG_FILE" ] \
        || die "Configurarea din browser nu este terminată încă."

    stop_bootstrap

    local root_script
    local termux_gid
    local termux_uid
    termux_uid="$(id -u)"
    termux_gid="$(id -g)"
    printf -v root_script \
        'chown -R %q:%q %q && { chown %q:%q %q 2>/dev/null || true; }' \
        "$termux_uid" "$termux_gid" "$BASE_DIR" \
        "$termux_uid" "$termux_gid" "$LOG_FILE"
    su -c "$root_script" >/dev/null \
        || die "Fișierele AdGuard Home nu au putut fi returnate utilizatorului Termux."

    chmod 700 "$BASE_DIR" "$WORK_DIR" "$CONFIG_DIR"
    chmod 600 "$CONFIG_FILE" "$SETTINGS_FILE"
    start_service
}


start_service() {
    load_config
    [ -x "$BINARY" ] \
        || die "Executabilul AdGuard Home lipsește. Rulează din nou instalatorul."

    mkdir -p "$WORK_DIR" "$CONFIG_DIR" "$DATA_DIR/runtime" "$DATA_DIR/logs"
    chmod 700 "$BASE_DIR" "$WORK_DIR" "$CONFIG_DIR" "$DATA_DIR/runtime"

    if [ ! -s "$CONFIG_FILE" ]; then
        ensure_dns_redirect
        start_bootstrap
        return 0
    fi

    [ ! -f "$BOOTSTRAP_PID_FILE" ] \
        || die "Terminarea configurării necesită: $0 finalize"

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
    stop_bootstrap
    remove_dns_redirect
    printf 'AdGuard Home a fost oprit, iar redirecționarea DNS a fost eliminată.\n'
}


status_service() {
    load_config
    local process_id
    if responds; then
        if [ -f "$BOOTSTRAP_PID_FILE" ]; then
            printf 'AdGuard Home online pentru configurarea inițială (temporar cu root).\n'
            [ -s "$CONFIG_FILE" ] \
                && printf 'Configurarea pare terminată; rulează: %s finalize\n' "$0"
            return 0
        fi
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
    finalize) finalize_setup ;;
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
        printf 'Utilizare: %s {start|stop|restart|finalize|status|firewall-enable|firewall-disable|firewall-status}\n' "$0" >&2
        exit 1
        ;;
esac
