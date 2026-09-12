#!/data/data/com.termux/files/usr/bin/bash

set -eu

DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
CADDY_DIR="$DATA_DIR/caddy"
CADDYFILE="$CADDY_DIR/Caddyfile"
PROXY_CONFIG="$CADDY_DIR/proxy.conf"
PID_FILE="$DATA_DIR/runtime/caddy.pid"
LOG_FILE="$DATA_DIR/logs/caddy.log"


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


load_proxy_config() {
    [ -r "$PROXY_CONFIG" ] \
        || die "HTTPS nu este configurat. Rulează scripts/configure-https.sh --help"
    # Fișier creat cu permisiuni 0600 de configurator.
    # shellcheck source=/dev/null
    source "$PROXY_CONFIG"
}


running_pid() {
    local process_id
    local command_line
    process_id="$(cat "$PID_FILE" 2>/dev/null || true)"

    case "$process_id" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    kill -0 "$process_id" 2>/dev/null || return 1
    command_line="$(
        tr '\0' ' ' < "/proc/$process_id/cmdline" 2>/dev/null || true
    )"

    case "$command_line" in
        *caddy*run*"$CADDYFILE"*)
            printf '%s\n' "$process_id"
            return 0
            ;;
    esac

    return 1
}


proxy_responds() {
    command -v curl >/dev/null 2>&1 || return 1
    curl \
        --silent \
        --fail \
        --insecure \
        --noproxy '*' \
        --max-time 5 \
        --output /dev/null \
        --connect-to "$HTTPS_HOST:$HTTPS_PORT:127.0.0.1:$HTTPS_PORT" \
        "https://$HTTPS_HOST:$HTTPS_PORT/api/health"
}


start_proxy() {
    load_proxy_config
    command -v caddy >/dev/null 2>&1 \
        || die "Caddy nu este instalat. Rulează: pkg install caddy"
    [ -r "$CADDYFILE" ] || die "lipsește configurația Caddy."

    local process_id
    if proxy_responds; then
        printf 'Proxy-ul HTTPS răspunde deja: https://%s:%s\n' \
            "$HTTPS_HOST" "$HTTPS_PORT"
        return 0
    fi

    if process_id="$(running_pid)"; then
        printf 'Caddy rulează (PID %s), dar HTTPS nu răspunde; se repornește.\n' \
            "$process_id"
        stop_proxy
    fi

    mkdir -p "$DATA_DIR/runtime" "$DATA_DIR/logs" "$CADDY_DIR/data" "$CADDY_DIR/config"
    rm -f "$PID_FILE"

    XDG_DATA_HOME="$CADDY_DIR/data" \
    XDG_CONFIG_HOME="$CADDY_DIR/config" \
        caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null

    nohup env \
        XDG_DATA_HOME="$CADDY_DIR/data" \
        XDG_CONFIG_HOME="$CADDY_DIR/config" \
        caddy run --config "$CADDYFILE" --adapter caddyfile \
        >> "$LOG_FILE" 2>&1 &
    process_id=$!
    printf '%s\n' "$process_id" > "$PID_FILE"
    chmod 600 "$PID_FILE"

    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if ! kill -0 "$process_id" 2>/dev/null; then
            rm -f "$PID_FILE"
            die "Caddy s-a oprit. Verifică $LOG_FILE"
        fi

        if proxy_responds; then
            printf 'Proxy HTTPS pornit: https://%s:%s\n' \
                "$HTTPS_HOST" "$HTTPS_PORT"
            return 0
        fi
        sleep 1
    done

    printf 'Avertisment: Caddy rulează, dar aplicația nu răspunde încă prin HTTPS.\n' >&2
    printf 'Verifică backend-ul și jurnalul: %s\n' "$LOG_FILE" >&2
    return 1
}


stop_proxy() {
    local process_id
    if ! process_id="$(running_pid)"; then
        rm -f "$PID_FILE"
        printf 'Proxy-ul HTTPS este deja oprit.\n'
        return 0
    fi

    kill "$process_id"
    local attempt
    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "$process_id" 2>/dev/null; then
            rm -f "$PID_FILE"
            printf 'Proxy-ul HTTPS a fost oprit.\n'
            return 0
        fi
        sleep 1
    done

    die "Caddy nu s-a oprit în timpul alocat (PID $process_id)."
}


status_proxy() {
    load_proxy_config
    local process_id

    if proxy_responds; then
        process_id="$(running_pid || true)"
        if [ -n "$process_id" ]; then
            printf 'HTTPS online: https://%s:%s (PID %s)\n' \
                "$HTTPS_HOST" "$HTTPS_PORT" "$process_id"
        else
            printf 'HTTPS online: https://%s:%s\n' \
                "$HTTPS_HOST" "$HTTPS_PORT"
        fi
        return 0
    fi

    if process_id="$(running_pid)"; then
        printf 'Caddy rulează (PID %s), dar aplicația nu răspunde prin HTTPS.\n' \
            "$process_id"
        return 1
    fi

    printf 'HTTPS oprit.\n'
    return 1
}


case "${1:-}" in
    start) start_proxy ;;
    stop) stop_proxy ;;
    restart)
        stop_proxy
        start_proxy
        ;;
    status) status_proxy ;;
    *)
        printf 'Utilizare: %s {start|stop|restart|status}\n' "$0" >&2
        exit 1
        ;;
esac
