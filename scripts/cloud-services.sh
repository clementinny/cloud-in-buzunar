#!/data/data/com.termux/files/usr/bin/bash

set -u

PROJECT_DIR="${CLOUD_PROJECT_DIR:-$HOME/projects/cloud-in-buzunar}"
DATA_DIR="${CLOUD_DATA_DIR:-$HOME/cloud-in-buzunar-data}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename -- "${BASH_SOURCE[0]}")"
LOG_DIR="$DATA_DIR/logs"
RUNTIME_DIR="$DATA_DIR/runtime"
CONFIG_FILE="$DATA_DIR/autostart.conf"
PYTHON="$PROJECT_DIR/.venv/bin/python"
GUNICORN="$PROJECT_DIR/.venv/bin/gunicorn"
WATCHDOG_PID_FILE="$RUNTIME_DIR/cloud-watchdog.pid"
WATCHDOG_HEARTBEAT_FILE="$RUNTIME_DIR/cloud-watchdog-heartbeat"
WATCHDOG_SAMPLE_FILE="$RUNTIME_DIR/cloud-watchdog-last-sample"
SERVICE_LOG="$LOG_DIR/cloud-services.log"
WATCHDOG_LOG="$LOG_DIR/cloud-watchdog.log"
BACKUP_LOG="$LOG_DIR/backup.log"
THERMAL_LOG="$LOG_DIR/thermal-guardian.log"
ALERT_LOG="$LOG_DIR/reliability-alerts.log"
THERMAL_SUSPENDED_DIR="$RUNTIME_DIR/thermal-suspended"
HTTPS_MANAGER="$PROJECT_DIR/scripts/cloud-https.sh"

START_SSHD=true
START_WEB=true
START_ARIA2=true
START_TRANSMISSION=true
START_AI=false
START_HTTPS=false
BACKUP_ENABLED=true
BACKUP_KEEP=3
BACKUP_INTERVAL_HOURS=24
WATCHDOG_INTERVAL_SECONDS=60
THERMAL_CHECK_TIMEOUT_SECONDS=45
ALERT_CHECK_INTERVAL_SECONDS=120

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


https_is_healthy() {
    [ -x "$HTTPS_MANAGER" ] \
        && "$HTTPS_MANAGER" status >/dev/null 2>&1
}


thermal_service_is_suspended() {
    [ -f "$THERMAL_SUSPENDED_DIR/$1" ]
}


run_thermal_guardian_check() {
    if [ ! -x "$PYTHON" ]; then
        log_message ERROR "Python din mediul virtual lipsește; istoricul nu poate fi colectat."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    local -a command=("$PYTHON" -m app.thermal_guardian check)

    if command_exists timeout; then
        command=(timeout "${THERMAL_CHECK_TIMEOUT_SECONDS:-45}" "${command[@]}")
    fi

    if "${command[@]}" >> "$THERMAL_LOG" 2>&1; then
        printf '%s\n' "$(date +%s)" > "$WATCHDOG_SAMPLE_FILE"
        chmod 600 "$WATCHDOG_SAMPLE_FILE"
        return 0
    fi

    log_message WARN \
        "Verificarea termică și salvarea istoricului au eșuat; vezi $THERMAL_LOG."
    return 1
}


run_reliability_alert_check() {
    if [ ! -x "$PYTHON" ]; then
        log_message ERROR "Python din mediul virtual lipsește; alertele nu pot fi evaluate."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    local -a command=("$PYTHON" -m app.reliability_alerts check)

    if command_exists timeout; then
        command=(timeout 90 "${command[@]}")
    fi

    if "${command[@]}" >> "$ALERT_LOG" 2>&1; then
        return 0
    fi

    log_message WARN "Evaluarea alertelor a eșuat; vezi $ALERT_LOG."
    return 1
}


validated_watchdog_interval() {
    local configured="${WATCHDOG_INTERVAL_SECONDS:-60}"

    case "$configured" in
        ''|*[!0-9]*)
            printf '60\n'
            return
            ;;
    esac

    if [ "$configured" -lt 15 ] || [ "$configured" -gt 3600 ]; then
        printf '60\n'
    else
        printf '%s\n' "$configured"
    fi
}


validated_alert_interval() {
    local configured="${ALERT_CHECK_INTERVAL_SECONDS:-120}"

    case "$configured" in
        ''|*[!0-9]*)
            printf '120\n'
            return
            ;;
    esac

    if [ "$configured" -lt 30 ] || [ "$configured" -gt 3600 ]; then
        printf '120\n'
    else
        printf '%s\n' "$configured"
    fi
}


write_watchdog_heartbeat() {
    local temporary_file="$WATCHDOG_HEARTBEAT_FILE.$$"

    printf '%s\n' "$(date +%s)" > "$temporary_file"
    chmod 600 "$temporary_file"
    mv -f "$temporary_file" "$WATCHDOG_HEARTBEAT_FILE"
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
        --access-logformat '%(h)s %(s)s %(L)s' \
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


start_https() {
    [ "$START_HTTPS" = true ] || return 0

    if https_is_healthy; then
        return 0
    fi

    if [ ! -x "$HTTPS_MANAGER" ]; then
        log_message WARN "Managerul HTTPS lipsește."
        return 1
    fi

    if "$HTTPS_MANAGER" start >> "$LOG_DIR/https-autostart.log" 2>&1; then
        log_message INFO "Proxy-ul HTTPS a fost pornit."
        return 0
    fi

    log_message ERROR "Proxy-ul HTTPS nu a putut fi pornit."
    return 1
}


stop_https() {
    if [ ! -x "$HTTPS_MANAGER" ]; then
        log_message WARN "Managerul HTTPS lipsește."
        return 1
    fi

    if "$HTTPS_MANAGER" stop >> "$LOG_DIR/https-autostart.log" 2>&1; then
        log_message INFO "Proxy-ul HTTPS a fost oprit intenționat."
        return 0
    fi

    log_message ERROR "Proxy-ul HTTPS nu a putut fi oprit."
    return 1
}


start_all() {
    start_sshd || true
    start_web || true
    start_aria2 || true
    start_transmission || true
    start_ai || true
    start_https || true
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


restart_https() {
    "$HTTPS_MANAGER" restart >> "$LOG_DIR/https-autostart.log" 2>&1
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
    local command_line
    process_id="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"

    case "$process_id" in
        ''|*[!0-9]*)
            return 1
            ;;
    esac

    kill -0 "$process_id" 2>/dev/null || return 1
    command_line="$(
        tr '\0' ' ' < "/proc/$process_id/cmdline" 2>/dev/null || true
    )"

    printf '%s\n' "$command_line" \
        | grep -Eq '(^|[ /])cloud-services\.sh watchdog([ ]|$)'
}


start_watchdog() {
    local attempt

    if watchdog_is_running; then
        return 0
    fi

    rm -f "$WATCHDOG_PID_FILE" "$WATCHDOG_HEARTBEAT_FILE"

    if [ ! -x "$PYTHON" ]; then
        log_message ERROR "Watchdog-ul nu poate porni: mediul virtual lipsește."
        return 1
    fi

    cd "$PROJECT_DIR" || return 1

    if ! "$PYTHON" -c \
        'from app.database import initialize_database; initialize_database()' \
        >> "$WATCHDOG_LOG" 2>&1; then
        log_message ERROR \
            "Watchdog-ul nu poate porni: baza de date nu a fost inițializată."
        return 1
    fi

    nohup "${BASH:-/data/data/com.termux/files/usr/bin/bash}" \
        "$SCRIPT_PATH" watchdog \
        </dev/null >> "$WATCHDOG_LOG" 2>&1 &

    for attempt in 1 2 3 4 5; do
        if watchdog_is_running; then
            log_message INFO "Watchdog-ul a fost pornit."
            return 0
        fi

        sleep 1
    done

    log_message ERROR "Watchdog-ul nu a putut fi pornit."
    return 1
}


stop_watchdog() {
    local process_id
    local attempt
    process_id="$(cat "$WATCHDOG_PID_FILE" 2>/dev/null || true)"

    if ! watchdog_is_running; then
        rm -f "$WATCHDOG_PID_FILE" "$WATCHDOG_HEARTBEAT_FILE"
        log_message INFO "Watchdog-ul este deja oprit."
        return 0
    fi

    kill "$process_id" 2>/dev/null || true

    for attempt in 1 2 3 4 5; do
        if ! kill -0 "$process_id" 2>/dev/null; then
            rm -f "$WATCHDOG_PID_FILE" "$WATCHDOG_HEARTBEAT_FILE"
            log_message INFO "Watchdog-ul a fost oprit intenționat."
            return 0
        fi

        sleep 1
    done

    log_message ERROR "Watchdog-ul nu s-a oprit în timpul alocat."
    return 1
}


run_watchdog() {
    if watchdog_is_running && [ "$(cat "$WATCHDOG_PID_FILE")" != "$$" ]; then
        log_message INFO "Există deja un watchdog activ; instanța duplicată se oprește."
        return 0
    fi

    printf '%s\n' "$$" > "$WATCHDOG_PID_FILE"
    chmod 600 "$WATCHDOG_PID_FILE"
    trap 'rm -f "$WATCHDOG_PID_FILE" "$WATCHDOG_HEARTBEAT_FILE"' EXIT INT TERM

    local web_failures=0
    local aria_failures=0
    local transmission_failures=0
    local ai_failures=0
    local https_failures=0
    local last_backup_check=0
    local last_alert_check=0
    local current_time
    local watchdog_interval
    local alert_interval

    log_message INFO "Watchdog-ul monitorizează serviciile."

    while true; do
        load_config
        watchdog_interval="$(validated_watchdog_interval)"
        alert_interval="$(validated_alert_interval)"

        if [ "${WATCHDOG_INTERVAL_SECONDS:-60}" != "$watchdog_interval" ]; then
            log_message WARN \
                "WATCHDOG_INTERVAL_SECONDS este invalid; se folosește 60 secunde."
        fi

        write_watchdog_heartbeat

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

        if [ "$START_HTTPS" = true ]; then
            if https_is_healthy; then
                https_failures=0
            else
                https_failures=$((https_failures + 1))

                if [ "$https_failures" -ge 3 ]; then
                    log_message WARN "Proxy-ul HTTPS nu răspunde; se repornește."
                    restart_https || true
                    https_failures=0
                fi
            fi
        fi

        current_time="$(date +%s)"

        if [ $((current_time - last_alert_check)) -ge "$alert_interval" ]; then
            run_reliability_alert_check || true
            last_alert_check="$current_time"
        fi

        if [ $((current_time - last_backup_check)) -ge 3600 ]; then
            start_backup_if_due
            last_backup_check="$current_time"
        fi

        sleep "$watchdog_interval"
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
    printf '  HTTPS:        %s\n' \
        "$(https_is_healthy && echo online || echo offline)"
    printf '  Watchdog:     %s\n' \
        "$(watchdog_is_running && echo online || echo offline)"
    if [ -r "$WATCHDOG_HEARTBEAT_FILE" ]; then
        printf '  Ultimul eșantion watchdog: %s\n' \
            "$(date -d "@$(cat "$WATCHDOG_HEARTBEAT_FILE")" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo necunoscut)"
    fi
    if [ -r "$WATCHDOG_SAMPLE_FILE" ]; then
        printf '  Ultimul istoric salvat: %s\n' \
            "$(date -d "@$(cat "$WATCHDOG_SAMPLE_FILE")" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo necunoscut)"
    fi
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
    watchdog-start)
        start_watchdog
        ;;
    watchdog-stop)
        stop_watchdog
        ;;
    watchdog-restart)
        stop_watchdog || true
        start_watchdog
        ;;
    watchdog-sample)
        if run_thermal_guardian_check; then
            log_message INFO "Eșantionul CPU/temperatură a fost salvat."
        else
            exit 1
        fi
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
    https-start)
        start_https
        ;;
    https-stop)
        stop_https
        ;;
    *)
        printf '%s\n' \
            "Utilizare: $0 {start|boot|watchdog|watchdog-start|watchdog-stop|watchdog-restart|watchdog-sample|status|check|aria2-start|aria2-stop|transmission-start|transmission-stop|ai-start|ai-stop|https-start|https-stop}"
        exit 1
        ;;
esac
