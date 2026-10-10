#!/bin/bash
# =============================================================================
# ChumaFlow Deployment & Domain Migration Script
#   • Migrates domain: sme.pritechmw.com → chumaflow.pritechmw.com
#   • Safe against self-overwrite during git pull (backs itself up)
#
# Recommended invocation (skip git & pip since both are already done):
#   sudo SKIP_GIT_PULL=1 SKIP_REQUIREMENTS_SYNC=1 \
#        GUNICORN_SERVICE=gunicorn-sme DAPHNE_SERVICE=daphne-sme \
#        ./migrate_domain.sh
# =============================================================================

set -euo pipefail

# -------------------------------
# Configuration
# -------------------------------
readonly OLD_DOMAIN="sme.pritechmw.com"
readonly NEW_DOMAIN="chumaflow.pritechmw.com"
readonly NEW_DOMAIN_WWW="www.chumaflow.pritechmw.com"
readonly SERVER_IP="204.168.251.91"

readonly PROJECT_DIR="/home/project/sme"
readonly VENV_DIR="${PROJECT_DIR}/venv"
readonly ENV_FILE="${PROJECT_DIR}/.env"
readonly NGINX_CONF="/etc/nginx/sites-available/sme"

readonly GIT_REPO="https://github.com/Izk-123/sme.git"
readonly GIT_BRANCH="main"

readonly LOG_FILE="/var/log/chumaflow_migration.log"
readonly TIMESTAMP=$(date +%Y%m%d_%H%M%S)
readonly BACKUP_DIR="/root/chumaflow_backup_${TIMESTAMP}"
readonly SELF_PATH="$(readlink -f "$0")"

GUNICORN_SERVICE="${GUNICORN_SERVICE:-}"
DAPHNE_SERVICE="${DAPHNE_SERVICE:-}"

readonly EXPLICIT_PACKAGES=(
    "Django" "channels" "channels-redis" "daphne" "reportlab"
    "openpyxl" "python-dotenv" "Pillow" "django-unfold" "psycopg2-binary"
    "gunicorn" "whitenoise" "redis" "requests" "twilio" "PyJWT" "aiohttp"
)

SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"
SKIP_REQUIREMENTS_SYNC="${SKIP_REQUIREMENTS_SYNC:-0}"

# -------------------------------
# Helpers
# -------------------------------
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"; echo "$msg" >> "$LOG_FILE"
}

error_exit() {
    log "ERROR: $1"
    log "Backup is at: ${BACKUP_DIR}"
    exit 1
}

check_root() { [[ $EUID -eq 0 ]] || error_exit "Run as root."; }

check_dependencies() {
    local missing=()
    for cmd in nginx certbot sed awk grep systemctl git curl python3 host; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || error_exit "Missing: ${missing[*]}"
    log "Dependencies verified."
}

find_service_for_project() {
    local prefix="$1"
    local dirname
    dirname=$(basename "$PROJECT_DIR")

    local f
    for f in /etc/systemd/system/${prefix}-*.service \
             /lib/systemd/system/${prefix}-*.service \
             /usr/lib/systemd/system/${prefix}-*.service; do
        [[ -f "$f" ]] || continue
        if grep -qE "WorkingDirectory=${PROJECT_DIR}|ExecStart=.*${PROJECT_DIR}" "$f"; then
            basename "$f" .service
            return 0
        fi
    done

    local candidate
    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-${dirname}\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    [[ -n "$candidate" ]] && { echo "$candidate"; return 0; }

    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-.*\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    [[ -n "$candidate" ]] && { log "  WARNING: no ${prefix} service tied to ${PROJECT_DIR}."; echo "$candidate"; return 0; }

    return 1
}

detect_services() {
    [[ -z "$GUNICORN_SERVICE" ]] && GUNICORN_SERVICE=$(find_service_for_project gunicorn || true)
    [[ -z "$DAPHNE_SERVICE" ]]   && DAPHNE_SERVICE=$(find_service_for_project daphne || true)
    [[ -z "$GUNICORN_SERVICE" ]] && GUNICORN_SERVICE="gunicorn-sme"
    [[ -z "$DAPHNE_SERVICE" ]]   && DAPHNE_SERVICE="daphne-sme"

    log "Services: GUNICORN=${GUNICORN_SERVICE}  DAPHNE=${DAPHNE_SERVICE}"
}

generate_unpinned_requirements() {
    local target="${1:-${PROJECT_DIR}/requirements.txt}"
    {
        echo "# ChumaFlow production dependencies (unpinned)."
        echo "#"
        printf '%s\n' "${EXPLICIT_PACKAGES[@]}"
    } > "$target"
}

# -------------------------------
# Pre-flight
# -------------------------------
preflight_checks() {
    log "=========================================="
    log "ChumaFlow Deployment + Domain Migration"
    log "Old:   $OLD_DOMAIN"
    log "New:   $NEW_DOMAIN"
    log "=========================================="

    check_root
    check_dependencies
    detect_services

    [[ -d "$PROJECT_DIR" ]] || error_exit "Missing: $PROJECT_DIR"
    [[ -d "$VENV_DIR" ]]    || error_exit "Missing: $VENV_DIR"
    [[ -f "$ENV_FILE" ]]    || error_exit "Missing: $ENV_FILE"
    [[ -f "$NGINX_CONF" ]]  || error_exit "Missing: $NGINX_CONF"

    log "Checking DNS for ${NEW_DOMAIN}..."
    if host "$NEW_DOMAIN" &>/dev/null; then
        local resolved
        resolved=$(host "$NEW_DOMAIN" | awk '/has address/ {print $4}' | head -1)
        log "  → $resolved"
        if [[ "$resolved" != "$SERVER_IP" ]]; then
            read -rp "  WARNING: expected ${SERVER_IP}. Continue? (y/N): " c
            [[ "$c" =~ ^[Yy]$ ]] || error_exit "Aborted."
        fi
    else
        read -rp "  WARNING: ${NEW_DOMAIN} does not resolve. Continue? (y/N): " c
        [[ "$c" =~ ^[Yy]$ ]] || error_exit "Aborted."
    fi
    log "Pre-flight OK."
}

# -------------------------------
# Backup
# -------------------------------
backup_files() {
    log "Backing up to ${BACKUP_DIR}..."
    mkdir -p "$BACKUP_DIR"

    cp "$NGINX_CONF" "${BACKUP_DIR}/nginx_sme.conf"
    cp "$ENV_FILE"   "${BACKUP_DIR}/env.backup"
    [[ -f "${PROJECT_DIR}/requirements.txt" ]]    && cp "${PROJECT_DIR}/requirements.txt"    "${BACKUP_DIR}/requirements.txt.backup"
    [[ -f "${PROJECT_DIR}/db.sqlite3" ]]          && cp "${PROJECT_DIR}/db.sqlite3"          "${BACKUP_DIR}/db.sqlite3.backup"
    [[ -f "${PROJECT_DIR}/config/settings.py" ]]  && cp "${PROJECT_DIR}/config/settings.py"  "${BACKUP_DIR}/settings.py.backup"
    [[ -d "${PROJECT_DIR}/.git" ]] && git -C "$PROJECT_DIR" rev-parse HEAD > "${BACKUP_DIR}/git_head.txt" 2>/dev/null || true

    log "Backup complete."
}

# -------------------------------
# Git pull — SELF-PRESERVING
# -------------------------------
pull_from_github() {
    [[ "$SKIP_GIT_PULL" == "1" ]] && { log "Skipping git pull."; return; }

    log "Pulling from GitHub..."

    # Preserve THIS script across the hard reset
    local self_bak="/tmp/chumaflow_self_${TIMESTAMP}.bak"
    cp "$SELF_PATH" "$self_bak"
    log "  Self backed up to ${self_bak}"

    cd "$PROJECT_DIR"

    if [[ ! -d ".git" ]]; then
        git init
        git remote add origin "$GIT_REPO"
        git fetch origin "$GIT_BRANCH"
        git checkout -B "$GIT_BRANCH" "origin/${GIT_BRANCH}"
    else
        local current
        current=$(git remote get-url origin 2>/dev/null || echo "")
        [[ "$current" != "$GIT_REPO" ]] && git remote set-url origin "$GIT_REPO"
    fi

    git fetch origin "$GIT_BRANCH"
    git checkout "$GIT_BRANCH" 2>/dev/null || git checkout -b "$GIT_BRANCH" "origin/${GIT_BRANCH}"

    cp "$ENV_FILE" "/tmp/chumaflow_env_${TIMESTAMP}.bak"
    git reset --hard "origin/${GIT_BRANCH}"

    # Restore .env and this script
    [[ -f "$ENV_FILE" ]] || cp "/tmp/chumaflow_env_${TIMESTAMP}.bak" "$ENV_FILE"
    cp "$self_bak" "$SELF_PATH"
    chmod +x "$SELF_PATH"
    log "  Restored local migrate_domain.sh after reset."
    log "  HEAD: $(git rev-parse --short HEAD)"
}

# -------------------------------
# Requirements
# -------------------------------
sync_requirements() {
    [[ "$SKIP_REQUIREMENTS_SYNC" == "1" ]] && { log "Skipping requirements sync."; return; }

    log "Synchronizing Python dependencies..."
    cd "$PROJECT_DIR"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    echo
    echo "requirements.txt strategy:"
    echo "  [1] Write UNPINNED explicit list (recommended)"
    echo "  [2] Write UNPINNED pip-freeze of the entire venv"
    echo "  [3] Keep the file that came from git"
    read -rp "Choice [1/2/3] (default 1): " choice
    choice="${choice:-1}"

    case "$choice" in
        1) cp requirements.txt "requirements.txt.${TIMESTAMP}.bak" 2>/dev/null || true
           generate_unpinned_requirements "requirements.txt" ;;
        2) cp requirements.txt "requirements.txt.${TIMESTAMP}.bak" 2>/dev/null || true
           { echo "# Auto-generated (unpinned)."
             pip freeze | grep -v '^-e' | grep -vE '^(pip|setuptools|wheel)==' \
                 | sed -E 's/==.*//; s/ @ .*//' | sort -u
           } > requirements.txt ;;
        3) : ;;
    esac

    [[ -s requirements.txt ]] && pip install --quiet --upgrade -r requirements.txt
    deactivate
    log "Dependency sync complete."
}

# -------------------------------
# .env hardening
# -------------------------------
upsert_var() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$val" '
            BEGIN { FS="=" } $1==k { print k "=" v; next } { print }
        ' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

update_env_file() {
    log "Hardening .env for production..."
    upsert_var "ALLOWED_HOSTS"        "${NEW_DOMAIN},${NEW_DOMAIN_WWW},${SERVER_IP},localhost,127.0.0.1"
    upsert_var "CSRF_TRUSTED_ORIGINS" "https://${NEW_DOMAIN},https://${NEW_DOMAIN_WWW}"
    upsert_var "BASE_URL"             "https://${NEW_DOMAIN}"
    upsert_var "DEBUG"                          "False"
    upsert_var "SECURE_SSL_REDIRECT"            "True"
    upsert_var "SECURE_HSTS_SECONDS"            "31536000"
    upsert_var "SECURE_HSTS_INCLUDE_SUBDOMAINS" "True"
    upsert_var "SECURE_HSTS_PRELOAD"            "True"
    upsert_var "USE_REDIS"                      "True"
    upsert_var "DB_ENGINE"                      "postgresql"
    log "  .env hardening complete."
}

# -------------------------------
# Django setup
# -------------------------------
django_setup() {
    log "Running Django setup..."
    cd "$PROJECT_DIR"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    export DJANGO_SETTINGS_MODULE=config.settings

    python - <<'PY' || error_exit "Django cannot connect to configured DB."
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection
print(f"    ENGINE = {connection.settings_dict['ENGINE']}")
print(f"    NAME   = {connection.settings_dict['NAME']}")
connection.ensure_connection()
print("    Connection: OK")
PY

    python manage.py migrate --noinput
    python manage.py seed_plans 2>/dev/null || true
    python manage.py collectstatic --noinput --clear
    python manage.py check --deploy 2>&1 | tee -a "$LOG_FILE" || true
    deactivate
    log "Django setup complete."
}

# -------------------------------
# Nginx
# -------------------------------
update_nginx_config() {
    log "Updating Nginx server_name..."

    # Replace any prior domain (sme.pritechmw.com, chumaflow.co, etc.)
    # in server_name lines with the new one.
    sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*(sme\.pritechmw\.com|chumaflow\.co)[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"

    # Rewrite any remaining old-domain references, but NEVER touch ssl_certificate paths.
    awk -v old1="sme.pritechmw.com" -v old2="chumaflow.co" -v new="$NEW_DOMAIN" '
        /ssl_certificate/ { print; next }
        { gsub(old1, new); gsub(old2, new); print }
    ' "$NGINX_CONF" > "${NGINX_CONF}.tmp" && mv "${NGINX_CONF}.tmp" "$NGINX_CONF"

    grep -nE 'server_name|if \(\$host' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"

    if nginx -t 2>&1 | tee -a "$LOG_FILE" | grep -q "test is successful"; then
        log "  Nginx config OK."
    else
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        error_exit "Nginx invalid — restored."
    fi
    systemctl reload nginx
}

# -------------------------------
# SSL
# -------------------------------
obtain_ssl_certificate() {
    log "Requesting SSL cert for ${NEW_DOMAIN} and ${NEW_DOMAIN_WWW}..."

    if certbot --nginx -d "${NEW_DOMAIN}" -d "${NEW_DOMAIN_WWW}" \
        --non-interactive --agree-tos --redirect 2>&1 | tee -a "$LOG_FILE"; then
        log "  SSL OK."
    else
        log "  Retrying with just ${NEW_DOMAIN}..."
        if certbot --nginx -d "${NEW_DOMAIN}" \
            --non-interactive --agree-tos --redirect 2>&1 | tee -a "$LOG_FILE"; then
            log "  SSL OK (main domain only)."
        else
            log "  WARNING: Certbot failed."
            log "    sudo certbot --nginx -d ${NEW_DOMAIN}"
        fi
    fi
    nginx -t 2>/dev/null && systemctl reload nginx || true
}

# -------------------------------
# Restart services (existence check via file, not list-unit-files)
# -------------------------------
service_exists() {
    local svc="$1"
    systemctl cat "$svc" &>/dev/null
}

restart_services() {
    log "Restarting services..."
    for svc in "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        if service_exists "$svc"; then
            systemctl restart "$svc"
            systemctl is-active --quiet "$svc" && log "  ${svc}: RUNNING" \
                || error_exit "${svc} failed to start."
        else
            log "  WARNING: ${svc} not found as a systemd unit — skipping."
        fi
    done
}

# -------------------------------
# Verify
# -------------------------------
verify_migration() {
    log "Verifying..."
    for unit in nginx "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        systemctl is-active --quiet "$unit" && log "  ${unit}: RUNNING" || log "  ${unit}: NOT RUNNING"
    done

    if curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | grep -q "HTTP"; then
        local code; code=$(curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | awk '{print $2}')
        log "  https://${NEW_DOMAIN} → HTTP ${code}"
    elif curl -sIk "http://${NEW_DOMAIN}" --max-time 10 | head -1 | grep -q "HTTP"; then
        log "  http://${NEW_DOMAIN} reachable (HTTPS pending Certbot)"
    else
        log "  ${NEW_DOMAIN} → no response"
    fi
}

# -------------------------------
# Summary
# -------------------------------
print_summary() {
    log "=========================================="
    log "DONE"
    log "=========================================="
    log "New domain: https://${NEW_DOMAIN}"
    log "Services:   ${GUNICORN_SERVICE}, ${DAPHNE_SERVICE}"
    log "Backup:     ${BACKUP_DIR}"
    log ""
    log "If HTTPS isn't working:"
    log "  sudo certbot --nginx -d ${NEW_DOMAIN} -d ${NEW_DOMAIN_WWW}"
}

# -------------------------------
# Main
# -------------------------------
main() {
    touch "$LOG_FILE"
    preflight_checks
    backup_files
    pull_from_github
    sync_requirements
    update_env_file
    django_setup
    update_nginx_config
    obtain_ssl_certificate
    restart_services
    verify_migration
    print_summary
}

main "$@"