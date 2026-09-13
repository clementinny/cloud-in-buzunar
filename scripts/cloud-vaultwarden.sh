#!/data/data/com.termux/files/usr/bin/bash

set -eu

PROJECT_DIR="${CLOUD_PROJECT_DIR:-$HOME/projects/cloud-in-buzunar}"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
BASE_DIR="$DATA_DIR/vaultwarden"
ROOTFS_DIR="$BASE_DIR/bundle/rootfs"
VAULT_DATA_DIR="$BASE_DIR/data"
CONFIG_FILE="$BASE_DIR/vaultwarden.env"
PID_FILE="$DATA_DIR/runtime/vaultwarden.pid"
LOG_FILE="$DATA_DIR/logs/vaultwarden.log"
BACKUP_DIR="$DATA_DIR/backups/vaultwarden"

VAULTWARDEN_DOMAIN=""
VAULTWARDEN_ADDRESS="127.0.0.1"
VAULTWARDEN_PORT=8222
VAULTWARDEN_SIGNUPS_ALLOWED=false
VAULTWARDEN_ADMIN_TOKEN=""
VAULTWARDEN_BACKUP_KEEP=7


die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}


load_config() {
    [ -r "$CONFIG_FILE" ] \
        || die "Vaultwarden nu este configurat. Rulează scripts/install-vaultwarden.sh --help"
    # Fișier local cu permisiuni 0600, creat de instalator.
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"

    [ -n "$VAULTWARDEN_DOMAIN" ] || die "VAULTWARDEN_DOMAIN lipsește."
    case "$VAULTWARDEN_PORT" in
        ''|*[!0-9]*) die "VAULTWARDEN_PORT este invalid." ;;
    esac
    [ "$VAULTWARDEN_PORT" -ge 1024 ] && [ "$VAULTWARDEN_PORT" -le 65535 ] \
        || die "VAULTWARDEN_PORT trebuie să fie între 1024 și 65535."
    case "$VAULTWARDEN_SIGNUPS_ALLOWED" in
        true|false) ;;
        *) die "VAULTWARDEN_SIGNUPS_ALLOWED trebuie să fie true sau false." ;;
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
        *proot*"$ROOTFS_DIR"*vaultwarden*)
            printf '%s\n' "$process_id"
            return 0
            ;;
    esac
    return 1
}


responds() {
    curl \
        --silent \
        --fail \
        --noproxy '*' \
        --max-time 5 \
        --output /dev/null \
        "http://$VAULTWARDEN_ADDRESS:$VAULTWARDEN_PORT/alive"
}


terminate_descendants() {
    local parent_id="$1"
    local child_id
    for child_id in $(pgrep -P "$parent_id" 2>/dev/null || true); do
        terminate_descendants "$child_id"
        kill "$child_id" 2>/dev/null || true
    done
}


start_service() {
    load_config
    command -v proot >/dev/null 2>&1 \
        || die "proot nu este instalat. Rulează: pkg install proot-distro"
    [ -x "$ROOTFS_DIR/vaultwarden" ] \
        || die "Imaginea Vaultwarden lipsește. Rulează din nou instalatorul."

    mkdir -p "$VAULT_DATA_DIR" "$DATA_DIR/runtime" "$DATA_DIR/logs"
    chmod 700 "$BASE_DIR" "$VAULT_DATA_DIR" "$DATA_DIR/runtime"

    if responds; then
        printf 'Vaultwarden răspunde deja: %s\n' "$VAULTWARDEN_DOMAIN"
        return 0
    fi

    local process_id
    if process_id="$(running_pid)"; then
        printf 'Procesul Vaultwarden %s nu răspunde; se repornește.\n' "$process_id"
        stop_service
    fi

    rm -f "$PID_FILE"
    local -a environment=(
        "DATA_FOLDER=/data"
        "DOMAIN=$VAULTWARDEN_DOMAIN"
        "ROCKET_ADDRESS=$VAULTWARDEN_ADDRESS"
        "ROCKET_PORT=$VAULTWARDEN_PORT"
        "SIGNUPS_ALLOWED=$VAULTWARDEN_SIGNUPS_ALLOWED"
        "WEB_VAULT_ENABLED=true"
        "LOG_LEVEL=warn"
    )
    if [ -n "$VAULTWARDEN_ADMIN_TOKEN" ]; then
        environment+=("ADMIN_TOKEN=$VAULTWARDEN_ADMIN_TOKEN")
    fi

    (
        unset LD_PRELOAD
        nohup env "${environment[@]}" \
            proot --kill-on-exit -0 \
                -r "$ROOTFS_DIR" \
                -b /proc \
                -b /dev \
                -b "$VAULT_DATA_DIR:/data" \
                -w / \
                /vaultwarden \
            >> "$LOG_FILE" 2>&1 &
        printf '%s\n' "$!" > "$PID_FILE"
    )
    chmod 600 "$PID_FILE"

    for _attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
        if responds; then
            printf 'Vaultwarden pornit: %s\n' "$VAULTWARDEN_DOMAIN"
            return 0
        fi
        sleep 1
    done

    tail -n 20 "$LOG_FILE" >&2 || true
    die "Vaultwarden nu a răspuns în timpul alocat."
}


stop_service() {
    local process_id
    if ! process_id="$(running_pid)"; then
        rm -f "$PID_FILE"
        printf 'Vaultwarden este deja oprit.\n'
        return 0
    fi

    # Vaultwarden este copilul procesului proot. Îl oprim primul pentru ca
    # SQLite să își închidă tranzacțiile înainte de backup sau restart.
    terminate_descendants "$process_id"
    kill "$process_id" 2>/dev/null || true
    for _attempt in 1 2 3 4 5 6 7 8 9 10; do
        if ! kill -0 "$process_id" 2>/dev/null; then
            rm -f "$PID_FILE"
            printf 'Vaultwarden a fost oprit.\n'
            return 0
        fi
        sleep 1
    done
    die "Vaultwarden nu s-a oprit în timpul alocat (PID $process_id)."
}


set_signups() {
    local value="$1"
    load_config
    local temporary_file="$CONFIG_FILE.tmp.$$"
    awk -v replacement="VAULTWARDEN_SIGNUPS_ALLOWED=$value" '
        BEGIN { found = 0 }
        /^VAULTWARDEN_SIGNUPS_ALLOWED=/ {
            print replacement
            found = 1
            next
        }
        { print }
        END { if (!found) print replacement }
    ' "$CONFIG_FILE" > "$temporary_file"
    chmod 600 "$temporary_file"
    mv "$temporary_file" "$CONFIG_FILE"
    printf 'Înregistrarea conturilor este acum: %s\n' "$value"
    stop_service || true
    start_service
}


create_backup() {
    load_config
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"

    local was_running=false
    if responds; then
        was_running=true
        stop_service
    fi

    local timestamp
    local archive
    local temporary_archive
    timestamp="$(date -u '+%Y%m%dT%H%M%SZ')"
    archive="$BACKUP_DIR/vaultwarden-$timestamp.tar.gz"
    temporary_archive="$archive.tmp"

    if tar -czf "$temporary_archive" -C "$VAULT_DATA_DIR" .; then
        chmod 600 "$temporary_archive"
        mv "$temporary_archive" "$archive"
        sha256sum "$archive" > "$archive.sha256"
        chmod 600 "$archive.sha256"
    else
        rm -f "$temporary_archive"
        [ "$was_running" = true ] && start_service || true
        die "Copia de siguranță Vaultwarden a eșuat."
    fi

    if [ "$was_running" = true ]; then
        start_service
    fi

    local keep="${VAULTWARDEN_BACKUP_KEEP:-7}"
    case "$keep" in
        ''|*[!0-9]*) keep=7 ;;
    esac
    if [ "$keep" -gt 0 ]; then
        find "$BACKUP_DIR" -maxdepth 1 -type f -name 'vaultwarden-*.tar.gz' \
            -printf '%T@ %p\n' \
            | sort -nr \
            | awk -v keep="$keep" 'NR > keep { sub(/^[^ ]+ /, ""); print }' \
            | while IFS= read -r old_archive; do
                [ -n "$old_archive" ] || continue
                rm -f -- "$old_archive" "$old_archive.sha256"
            done
    fi

    printf 'Backup Vaultwarden creat: %s\n' "$archive"
}


status_service() {
    load_config
    local process_id
    if responds; then
        process_id="$(running_pid || true)"
        printf 'Vaultwarden online: %s' "$VAULTWARDEN_DOMAIN"
        [ -n "$process_id" ] && printf ' (PID %s)' "$process_id"
        printf '\nÎnregistrări deschise: %s\n' "$VAULTWARDEN_SIGNUPS_ALLOWED"
        return 0
    fi
    printf 'Vaultwarden oprit.\n'
    return 1
}


case "${1:-}" in
    start) start_service ;;
    stop) stop_service ;;
    restart)
        stop_service || true
        start_service
        ;;
    status) status_service ;;
    signup-open) set_signups true ;;
    signup-close) set_signups false ;;
    backup) create_backup ;;
    *)
        printf 'Utilizare: %s {start|stop|restart|status|signup-open|signup-close|backup}\n' "$0" >&2
        exit 1
        ;;
esac
