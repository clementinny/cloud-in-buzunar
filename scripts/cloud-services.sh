#!/data/data/com.termux/files/usr/bin/bash

set -u

PROJECT_DIR="${CLOUD_PROJECT_DIR:-$HOME/projects/cloud-in-buzunar}"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
LOG_DIR="$DATA_DIR/logs"
RUNTIME_DIR="$DATA_DIR/runtime"
CONFIG_FILE="$DATA_DIR/autostart.conf"
PYTHON="$PROJECT_DIR/.venv/bin/python"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
WATCHDOG_PID_FILE="$RUNTIME_DIR/cloud-watchdog.pid"
SERVICE_LOG="$LOG_DIR/cloud-services.log"
WATCHDOG_LOG="$LOG_DIR/cloud-watchdog.log"
BACKUP_LOG="$LOG_DIR/backup.log"
THERMAL_LOG="$LOG_DIR/thermal-guardian.log"
THERMAL_SUSPENDED_DIR="$RUNTIME_DIR/thermal-suspended"

START_SSHD=true
START_WEB=true
START_ARIA2=true
START_TRANSMISSION=true
START_AI=false
BACKUP_ENABLED=true
BACKUP_KEEP=3
BACKUP_INTERVAL_HOURS=24
WATCHDOG_INTERVAL_SECONDS=60

mkdir -p "$LOG_DIR" "$RUNTIME_DIR"


load_config() {
    if [ -f "$CONFIG_FILE" ]; then
        # This file is owned and editable only by the Termux user.
        # shellcheck source=/dev/null
        source "$CONFIG_FILE"
    fi
}


load_config


log_message() {
    local level="$1"
    shift
    local line
    line="$(date '+%Y-%m-%d %H:%M:%S') [$level] $*"
    printf '%s\n' "$line" >> "$SERVICE_LOG"
    printf '%s\n' "$line"
}


command_exists() {
    command -v "$1" >/dev/null 2>&1
}


process_matches() {
    pgrep -f "$1" >/dev/null 2>&1
}


port_responds() {
    local port="$1"

    if ! command_exists curl; then
        return 1
    fi

    curl \
        --silent \
        --show-error \
        --max-time 3 \
        --output /dev/null \
        "http://127.0.0.1:$port/" \
        >/dev/null 2>&1
}


web_is_healthy() {
    command_exists curl && curl \
        --silent \
        --fail \
        --max-time 5 \
        --output /dev/null \
        "http://127.0.0.1:8080/api/health"
}


ai_is_healthy() {
    command_exists curl && curl \
        --silent \
        --fail \
        --max-time 5 \
        --output /dev/null \
        "http://127.0.0.1:8081/health"
}


thermal_service_is_suspended() {
    [ -f "$THERMAL_SUSPENDED_DIR/$1" ]
}


run_thermal_guardian_check() {
    [ -x "$PYTHON" ] || return 0
    cd "$PROJECT_DIR" || return 1

    "$PYTHON" -m app.thermal_guardian check \
        >> "$THERMAL_LOG" 2>&1 || \
        log_message WARN "Verificarea termică a eșuat."
}


start_sshd() {
    [ "$START_SSHD" = true ] || return 0

    if process_matches '(^|/)sshd( |$)'; then
        return 0
    fi

    if ! command_exists sshd; then
        log_message WARN "sshd nu este instalat."
        return 1
    fi

    sshd
    log_message INFO "sshd a fost pornit."
}


start_web() {
    [ "$START_WEB" = true ] || return 0

    if process_matches "$PROJECT_DIR/.venv/bin/gunicorn.*app.main:app" \
        && web_is_healthy; then
        return 0
    fi

    if process_matches "$PROJECT_DIR/.venv/bin/gunicorn.*app.main:app"; then
        stop_matching_processes \
            "$PROJECT_DIR/.venv/bin/gunicorn.*app.main:app"
        sleep 2
    fi

    if [ ! -x "$GUNICORN" ] || [ ! -x "$PYTHON" ]; then
        log_message ERROR "Mediul virtual sau Gunicorn lipsește."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    nohup "$GUNICORN" \
        --chdir "$PROJECT_DIR" \
        --bind 0.0.0.0:8080 \
        --workers 1 \
        --threads 4 \
        --timeout 180 \
        --access-logfile "$LOG_DIR/gunicorn-access.log" \
        --error-logfile "$LOG_DIR/gunicorn-error.log" \
        app.main:app \
        >/dev/null 2>&1 &

    local attempt

    for attempt in 1 2 3 4 5 6 7 8 9 10; do
        if web_is_healthy; then
            log_message INFO "Serverul web a fost pornit."
            return 0
        fi

        sleep 1
    done

    log_message ERROR "Serverul web nu a devenit disponibil."
    return 1
}


start_aria2() {
    [ "$START_ARIA2" = true ] || return 0

    if process_matches '(^|/)aria2c( |$)' && port_responds 6800; then
        return 0
    fi

    if process_matches '(^|/)aria2c( |$)'; then
        stop_matching_processes '(^|/)aria2c( |$)'
        sleep 1
    fi

    local config_file="$DATA_DIR/aria2/aria2.conf"
    local secret_file="$DATA_DIR/aria2/rpc-secret"

    if ! command_exists aria2c; then
        log_message WARN "aria2c nu este instalat."
        return 1
    fi

    if [ ! -r "$config_file" ] || [ ! -r "$secret_file" ]; then
        log_message WARN "Configurația sau secretul aria2 lipsește."
        return 1
    fi

    local rpc_secret
    rpc_secret="$(tr -d '\r\n' < "$secret_file")"

    aria2c \
        --conf-path="$config_file" \
        --rpc-secret="$rpc_secret" \
        --daemon=true \
        >/dev/null 2>&1
    unset rpc_secret
    sleep 1

    if port_responds 6800; then
        log_message INFO "aria2 a fost pornit."
        return 0
    fi

    log_message ERROR "aria2 nu a devenit disponibil."
    return 1
}


stop_aria2() {
    if ! process_matches '(^|/)aria2c( |$)'; then
        log_message INFO "aria2 este deja oprit."
        return 0
    fi

    stop_matching_processes '(^|/)aria2c( |$)'

    local attempt

    for attempt in 1 2 3 4 5; do
        if ! process_matches '(^|/)aria2c( |$)'; then
            log_message INFO "aria2 a fost oprit intenționat."
            return 0
        fi

        sleep 1
    done

    log_message ERROR "aria2 nu s-a oprit în timpul alocat."
    return 1
}


start_transmission() {
    [ "$START_TRANSMISSION" = true ] || return 0

    if process_matches '(^|/)transmission-daemon( |$)' \
        && port_responds 9091; then
        return 0
    fi

    if process_matches '(^|/)transmission-daemon( |$)'; then
        stop_matching_processes '(^|/)transmission-daemon( |$)'
        sleep 2
    fi

    if ! command_exists transmission-daemon; then
        log_message WARN "Transmission nu este instalat."
        return 1
    fi

    local config_dir="$DATA_DIR/transmission"
    local download_dir="$DATA_DIR/downloads/transmission"
    mkdir -p "$config_dir" "$download_dir"

    transmission-daemon \
        --config-dir "$config_dir" \
        --download-dir "$download_dir" \
        --rpc-bind-address 127.0.0.1 \
        --port 9091 \
        >> "$LOG_DIR/transmission.log" 2>&1
    sleep 2

    if port_responds 9091; then
        log_message INFO "Transmission a fost pornit."
        return 0
    fi

    log_message ERROR "Transmission nu a devenit disponibil."
    return 1
}


stop_transmission() {
    if ! process_matches '(^|/)transmission-daemon( |$)'; then
        log_message INFO "Transmission este deja oprit."
        return 0
    fi

    stop_matching_processes '(^|/)transmission-daemon( |$)'

    local attempt

    for attempt in 1 2 3 4 5; do
        if ! process_matches '(^|/)transmission-daemon( |$)'; then
            log_message INFO "Transmission a fost oprit intenționat."
            return 0
        fi

        sleep 1
    done

    log_message ERROR "Transmission nu s-a oprit în timpul alocat."
    return 1
}


start_ai() {
    [ "$START_AI" = true ] || return 0

    if ai_is_healthy; then
        return 0
    fi

    if [ ! -x "$PYTHON" ]; then
        log_message ERROR "Python din mediul virtual lipsește."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    if "$PYTHON" -m app.ai_runtime start >> "$LOG_DIR/ai-autostart.log" 2>&1; then
        log_message INFO "AI-ul local a fost pornit."
        return 0
    fi

    log_message ERROR "AI-ul local nu a putut fi pornit."
    return 1
}


stop_ai() {
    if [ ! -x "$PYTHON" ]; then
        log_message ERROR "Python din mediul virtual lipsește."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    if "$PYTHON" -m app.ai_runtime stop >> "$LOG_DIR/ai-autostart.log" 2>&1; then
        log_message INFO "AI-ul local a fost oprit intenționat."
        return 0
    fi

    log_message ERROR "AI-ul local nu a putut fi oprit."
    return 1
}


start_all() {
    start_sshd || true
    start_web || true
    start_aria2 || true
    start_transmission || true
    start_ai || true
}


stop_matching_processes() {
    local pattern="$1"
    local process_id

    while read -r process_id; do
        [ -n "$process_id" ] && kill "$process_id" 2>/dev/null || true
    done < <(pgrep -f "$pattern" 2>/dev/null || true)
}


restart_web() {
    stop_matching_processes \
        "$PROJECT_DIR/.venv/bin/gunicorn.*app.main:app"
    sleep 2
    start_web
}


restart_aria2() {
    stop_matching_processes '(^|/)aria2c( |$)'
    sleep 1
    start_aria2
}


restart_transmission() {
    stop_matching_processes '(^|/)transmission-daemon( |$)'
    sleep 2
    start_transmission
}


restart_ai() {
    "$PYTHON" -m app.ai_runtime stop \
        >> "$LOG_DIR/ai-autostart.log" 2>&1 || true
    start_ai
}


backup_is_recent() {
    local backup_dir="$DATA_DIR/backups"
    local interval_minutes=$((BACKUP_INTERVAL_HOURS * 60))

    [ -d "$backup_dir" ] && find "$backup_dir" \
        -type f \
        -name 'cloud-in-buzunar-*.tar.gz' \
        -mmin "-$interval_minutes" \
        -print \
        -quit \
        | grep -q .
}


start_backup_if_due() {
    [ "$BACKUP_ENABLED" = true ] || return 0
    backup_is_recent && return 0

    local lock_dir="$RUNTIME_DIR/backup.lock"

    if ! mkdir "$lock_dir" 2>/dev/null; then
        return 0
    fi

    (
        trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
        cd "$PROJECT_DIR" || exit 1
        log_message INFO "Pornește copia de siguranță programată."

        if "$PYTHON" -m app.backup create --keep "$BACKUP_KEEP" \
            >> "$BACKUP_LOG" 2>&1; then
            log_message INFO "Copia de siguranță programată s-a terminat."
        else
            log_message ERROR "Copia de siguranță programată a eșuat."
        fi
    ) &
}


watchdog_is_running() {
    local process_id
    process_id="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"

    [ -n "$process_id" ] \
        && kill -0 "$process_id" 2>/dev/null \
        && tr '\0' ' ' < "/proc/$process_id/cmdline" 2>/dev/null \
            | grep -q 'cloud-services.sh watchdog'
}


start_watchdog() {
    if watchdog_is_running; then
        return 0
    fi

    rm -f "$WATCHDOG_PID_FILE"
    nohup "$0" watchdog >> "$WATCHDOG_LOG" 2>&1 &
    sleep 1

    if watchdog_is_running; then
        log_message INFO "Watchdog-ul a fost pornit."
        return 0
    fi

    log_message ERROR "Watchdog-ul nu a putut fi pornit."
    return 1
}


run_watchdog() {
    printf '%s\n' "$$" > "$WATCHDOG_PID_FILE"
    chmod 600 "$WATCHDOG_PID_FILE"
    trap 'rm -f "$WATCHDOG_PID_FILE"' EXIT INT TERM

    local web_failures=0
    local aria_failures=0
    local transmission_failures=0
    local ai_failures=0
    local last_backup_check=0
    local current_time

    log_message INFO "Watchdog-ul monitorizează serviciile."

    while true; do
        load_config

        if [ "$START_SSHD" = true ] \
            && ! process_matches '(^|/)sshd( |$)'; then
            log_message WARN "sshd s-a oprit; se încearcă repornirea."
            start_sshd || true
        fi

        if [ "$START_WEB" = true ]; then
            if web_is_healthy; then
                web_failures=0
            else
                web_failures=$((web_failures + 1))

                if [ "$web_failures" -ge 3 ]; then
                    log_message WARN \
                        "Serverul web nu răspunde; se repornește."
                    restart_web || true
                    web_failures=0
                fi
            fi
        fi

        run_thermal_guardian_check

        if [ "$START_ARIA2" = true ] \
            && ! thermal_service_is_suspended aria2; then
            if port_responds 6800; then
                aria_failures=0
            else
                aria_failures=$((aria_failures + 1))

                if [ "$aria_failures" -ge 3 ]; then
                    log_message WARN "aria2 nu răspunde; se repornește."
                    restart_aria2 || true
                    aria_failures=0
                fi
            fi
        fi

        if [ "$START_TRANSMISSION" = true ] \
            && ! thermal_service_is_suspended transmission; then
            if port_responds 9091; then
                transmission_failures=0
            else
                transmission_failures=$((transmission_failures + 1))

                if [ "$transmission_failures" -ge 3 ]; then
                    log_message WARN \
                        "Transmission nu răspunde; se repornește."
                    restart_transmission || true
                    transmission_failures=0
                fi
            fi
        fi

        if [ "$START_AI" = true ] \
            && ! thermal_service_is_suspended ai; then
            if ai_is_healthy; then
                ai_failures=0
            else
                ai_failures=$((ai_failures + 1))

                if [ "$ai_failures" -ge 3 ]; then
                    log_message WARN "AI-ul nu răspunde; se repornește."
                    restart_ai || true
                    ai_failures=0
                fi
            fi
        fi

        current_time="$(date +%s)"

        if [ $((current_time - last_backup_check)) -ge 3600 ]; then
            start_backup_if_due
            last_backup_check="$current_time"
        fi

        sleep "$WATCHDOG_INTERVAL_SECONDS"
    done
}


print_service_status() {
    printf 'CloudInBuzunar\n'
    printf '  Web:          %s\n' \
        "$(web_is_healthy && echo online || echo offline)"
    printf '  SSH:          %s\n' \
        "$(process_matches '(^|/)sshd( |$)' && echo online || echo offline)"
    printf '  aria2:        %s\n' \
        "$(port_responds 6800 && echo online || echo offline)"
    printf '  Transmission: %s\n' \
        "$(port_responds 9091 && echo online || echo offline)"
    printf '  AI:           %s\n' \
        "$(ai_is_healthy && echo online || echo offline)"
    printf '  Watchdog:     %s\n' \
        "$(watchdog_is_running && echo online || echo offline)"
    printf '  Protecție termică: %s\n' \
        "$($PYTHON -m app.thermal_guardian status 2>/dev/null || echo indisponibil)"
    printf '  AI la boot:   %s\n' "$START_AI"
    printf '  Backup zilnic: %s (păstrează %s)\n' \
        "$BACKUP_ENABLED" "$BACKUP_KEEP"
}


case "${1:-}" in
    start)
        start_all
        start_watchdog
        ;;
    boot)
        start_all
        start_watchdog
        ;;
    watchdog)
        run_watchdog
        ;;
    status)
        print_service_status
        ;;
    check)
        start_all
        start_backup_if_due
        ;;
    transmission-start)
        start_transmission
        ;;
    transmission-stop)
        stop_transmission
        ;;
    aria2-start)
        start_aria2
        ;;
    aria2-stop)
        stop_aria2
        ;;
    ai-start)
        start_ai
        ;;
    ai-stop)
        stop_ai
        ;;
    *)
        printf '%s\n' \
            "Utilizare: $0 {start|boot|watchdog|status|check|aria2-start|aria2-stop|transmission-start|transmission-stop|ai-start|ai-stop}"
        exit 1
        ;;
esac
