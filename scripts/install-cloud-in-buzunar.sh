#!/data/data/com.termux/files/usr/bin/bash

set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "${BASH_SOURCE[0]%/*}" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DATA_DIR="$HOME/cloud-in-buzunar-data"

WITH_AI=false
SKIP_PACKAGES=false
SKIP_AUTOSTART=false
DRY_RUN=false
IMPORT_ARCHIVE=""
ADMIN_USERNAME=""

usage() {
    cat <<'EOF'
Instalare completă CloudInBuzunar pentru Termux/aarch64.

Utilizare:
  scripts/install-cloud-in-buzunar.sh [opțiuni]

Opțiuni:
  --with-ai              Instalează și llama.cpp; AI rămâne activ la boot.
  --without-ai           Nu instalează llama.cpp (implicit).
  --import ARHIVĂ        Importă o migrare după instalare și validare.
  --admin UTILIZATOR     Creează un administrator și solicită parola în siguranță.
  --skip-packages        Nu rulează pkg install.
  --skip-autostart       Nu instalează scriptul Termux:Boot.
  --dry-run              Afișează operațiile fără să modifice telefonul.
  -h, --help             Afișează acest ajutor.

Scriptul trebuie rulat din copia locală a repository-ului. Nu descarcă și nu
execută scripturi de pe internet. Pentru --import, arhiva trebuie să existe
deja local și confirmarea folosește exact numele ei.
EOF
}

die() {
    printf 'Eroare: %s\n' "$*" >&2
    exit 1
}

print_command() {
    printf '  '
    printf '%q ' "$@"
    printf '\n'
}

run() {
    if "$DRY_RUN"; then
        print_command "$@"
    else
        "$@"
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --with-ai)
            WITH_AI=true
            ;;
        --without-ai)
            WITH_AI=false
            ;;
        --import)
            [ "$#" -ge 2 ] || die "--import necesită calea arhivei."
            IMPORT_ARCHIVE="$2"
            shift
            ;;
        --admin)
            [ "$#" -ge 2 ] || die "--admin necesită un nume de utilizator."
            ADMIN_USERNAME="$2"
            shift
            ;;
        --skip-packages)
            SKIP_PACKAGES=true
            ;;
        --skip-autostart)
            SKIP_AUTOSTART=true
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            usage >&2
            die "Opțiune necunoscută: $1"
            ;;
    esac
    shift
done

[ "$(uname -m)" = "aarch64" ] \
    || die "Este necesar un dispozitiv Android aarch64."
command -v pkg >/dev/null 2>&1 \
    || die "Comanda pkg lipsește; rulează scriptul în Termux."
case "${PREFIX:-}" in
    /data/data/*/files/usr) ;;
    *) die "Mediul curent nu pare o instalare Termux validă." ;;
esac

[ -f "$PROJECT_DIR/requirements.txt" ] \
    || die "requirements.txt lipsește din $PROJECT_DIR."
[ -f "$PROJECT_DIR/app/main.py" ] \
    || die "Aplicația CloudInBuzunar lipsește din $PROJECT_DIR."

if [ -n "$ADMIN_USERNAME" ] \
    && ! [[ "$ADMIN_USERNAME" =~ ^[A-Za-z0-9_.-]{3,32}$ ]]; then
    die "administratorul trebuie să aibă 3-32 caractere sigure."
fi

if [ -n "$IMPORT_ARCHIVE" ]; then
    if [[ "$IMPORT_ARCHIVE" != /* ]]; then
        IMPORT_ARCHIVE="$(pwd)/$IMPORT_ARCHIVE"
    fi
    [ -f "$IMPORT_ARCHIVE" ] \
        || die "Arhiva de import nu există: $IMPORT_ARCHIVE"
fi

cd "$PROJECT_DIR"

printf 'CloudInBuzunar: instalare locală verificată\n'
printf 'Proiect: %s\n' "$PROJECT_DIR"
printf 'Date: %s\n' "$DATA_DIR"
printf 'AI la boot: %s\n' "$WITH_AI"

if ! "$SKIP_PACKAGES"; then
    packages=(python git openssh aria2 transmission ffmpeg termux-api caddy)
    if "$WITH_AI"; then
        packages+=(llama-cpp)
    fi
    run pkg update -y
    run pkg install -y "${packages[@]}"
fi

run mkdir -p \
    "$DATA_DIR" \
    "$DATA_DIR/backups" \
    "$DATA_DIR/logs" \
    "$DATA_DIR/runtime" \
    "$DATA_DIR/aria2" \
    "$DATA_DIR/downloads/aria2" \
    "$DATA_DIR/downloads/transmission" \
    "$DATA_DIR/uploads" \
    "$DATA_DIR/media" \
    "$DATA_DIR/models" \
    "$DATA_DIR/monitor-recordings"
run chmod 700 \
    "$DATA_DIR" \
    "$DATA_DIR/backups" \
    "$DATA_DIR/logs" \
    "$DATA_DIR/runtime" \
    "$DATA_DIR/aria2" \
    "$DATA_DIR/downloads" \
    "$DATA_DIR/downloads/aria2" \
    "$DATA_DIR/downloads/transmission" \
    "$DATA_DIR/uploads" \
    "$DATA_DIR/media" \
    "$DATA_DIR/models" \
    "$DATA_DIR/monitor-recordings"

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
    run python -m venv "$PROJECT_DIR/.venv"
fi

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
if ! "$DRY_RUN"; then
    [ -x "$VENV_PYTHON" ] || die "Mediul virtual nu a fost creat corect."
fi
run "$VENV_PYTHON" -m pip install --upgrade pip
run "$VENV_PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
run "$VENV_PYTHON" -c \
    'from app.database import initialize_database; initialize_database(); print("Database initialized")'

ARIA2_CONFIG="$DATA_DIR/aria2/aria2.conf"
ARIA2_SECRET="$DATA_DIR/aria2/rpc-secret"

if [ ! -f "$ARIA2_SECRET" ]; then
    if "$DRY_RUN"; then
        printf '  [generează secret aria2 în %s]\n' "$ARIA2_SECRET"
    else
        "$VENV_PYTHON" -c \
            'import secrets; print(secrets.token_urlsafe(32))' \
            > "$ARIA2_SECRET"
        chmod 600 "$ARIA2_SECRET"
    fi
fi

if [ ! -f "$ARIA2_CONFIG" ]; then
    if "$DRY_RUN"; then
        printf '  [creează configurația aria2 în %s]\n' "$ARIA2_CONFIG"
    else
        cat > "$ARIA2_CONFIG" <<EOF
enable-rpc=true
rpc-listen-all=false
rpc-listen-port=6800
rpc-save-upload-metadata=true
continue=true
file-allocation=none
max-concurrent-downloads=3
dir=$DATA_DIR/downloads/aria2
EOF
        chmod 600 "$ARIA2_CONFIG"
    fi
fi

run chmod +x \
    "$PROJECT_DIR/scripts/cloud-services.sh" \
    "$PROJECT_DIR/scripts/install-termux-autostart.sh" \
    "$PROJECT_DIR/scripts/install-cloud-in-buzunar.sh" \
    "$PROJECT_DIR/scripts/cloud-migrate.py" \
    "$PROJECT_DIR/scripts/configure-https.sh" \
    "$PROJECT_DIR/scripts/cloud-https.sh"

if [ -n "$IMPORT_ARCHIVE" ]; then
    archive_name="$(basename "$IMPORT_ARCHIVE")"
    run "$VENV_PYTHON" "$PROJECT_DIR/scripts/cloud-migrate.py" verify "$IMPORT_ARCHIVE"
    run "$VENV_PYTHON" "$PROJECT_DIR/scripts/cloud-migrate.py" import \
        "$IMPORT_ARCHIVE" --yes --confirm "$archive_name"
fi

if [ -n "$ADMIN_USERNAME" ]; then
    run "$VENV_PYTHON" -m app.manage_users create \
        "$ADMIN_USERNAME" --role admin
fi

if ! "$SKIP_AUTOSTART"; then
    if "$WITH_AI"; then
        run "$PROJECT_DIR/scripts/install-termux-autostart.sh" --with-ai
    else
        run "$PROJECT_DIR/scripts/install-termux-autostart.sh" --without-ai
    fi
fi

printf '\nInstalarea CloudInBuzunar este pregătită.\n'
printf 'Verificare: %s/scripts/cloud-services.sh status\n' "$PROJECT_DIR"
printf 'Administrare utilizatori: %s -m app.manage_users --help\n' "$VENV_PYTHON"
printf 'HTTPS: %s/scripts/configure-https.sh --help\n' "$PROJECT_DIR"
if "$SKIP_AUTOSTART"; then
    printf 'Autostartul a fost omis explicit.\n'
else
    printf 'Deschide Termux:Boot o dată și dezactivează optimizarea bateriei.\n'
fi
