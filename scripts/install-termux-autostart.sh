#!/data/data/com.termux/files/usr/bin/bash

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$HOME/cloud-in-buzunar-data"
CONFIG_FILE="$DATA_DIR/autostart.conf"
BOOT_DIR="$HOME/.termux/boot"
BOOT_SCRIPT="$BOOT_DIR/20-cloud-in-buzunar"
MANAGER="$PROJECT_DIR/scripts/cloud-services.sh"
START_AI=false

if [ "${1:-}" = "--with-ai" ]; then
    START_AI=true
elif [ -n "${1:-}" ] && [ "${1:-}" != "--without-ai" ]; then
    printf 'Utilizare: %s [--with-ai|--without-ai]\n' "$0"
    exit 1
fi

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ] \
    || [ ! -x "$PROJECT_DIR/.venv/bin/gunicorn" ]; then
    printf 'Eroare: mediul virtual al proiectului nu este pregătit.\n' >&2
    exit 1
fi

mkdir -p "$DATA_DIR/logs" "$DATA_DIR/runtime" "$BOOT_DIR"
chmod 700 "$DATA_DIR/runtime" "$BOOT_DIR"
chmod +x "$MANAGER"

if [ ! -f "$CONFIG_FILE" ]; then
    cat > "$CONFIG_FILE" <<EOF
# CloudInBuzunar autostart settings
START_SSHD=true
START_WEB=true
START_ARIA2=true
START_TRANSMISSION=true
START_AI=$START_AI
BACKUP_ENABLED=true
BACKUP_KEEP=3
BACKUP_INTERVAL_HOURS=24
WATCHDOG_INTERVAL_SECONDS=60
EOF
else
    if grep -q '^START_AI=' "$CONFIG_FILE"; then
        sed -i "s/^START_AI=.*/START_AI=$START_AI/" "$CONFIG_FILE"
    else
        printf 'START_AI=%s\n' "$START_AI" >> "$CONFIG_FILE"
    fi
fi

chmod 600 "$CONFIG_FILE"

{
    printf '#!/data/data/com.termux/files/usr/bin/bash\n\n'
    printf 'export CLOUD_PROJECT_DIR=%q\n' "$PROJECT_DIR"
    printf 'termux-wake-lock\n'
    printf 'sleep 15\n'
    printf 'exec %q boot\n' "$MANAGER"
} > "$BOOT_SCRIPT"

chmod 700 "$BOOT_SCRIPT"

"$MANAGER" start

printf '\nAutostart CloudInBuzunar a fost instalat.\n'
printf 'Script boot: %s\n' "$BOOT_SCRIPT"
printf 'Configurație: %s\n' "$CONFIG_FILE"
printf 'AI pornit automat: %s\n' "$START_AI"
printf '\nInstalează Termux:Boot din aceeași sursă ca Termux,\n'
printf 'apoi deschide aplicația Termux:Boot o singură dată.\n'
printf 'Dezactivează optimizarea bateriei pentru Termux și Termux:Boot.\n'
