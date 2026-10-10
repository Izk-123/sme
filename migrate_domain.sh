#!/bin/bash
# =============================================================================
# ChumaFlow Deployment & Domain Migration Script
#   • Pulls latest code from GitHub: https://github.com/Izk-123/sme.git
#   • Writes an UNPINNED requirements.txt (package names only, no versions)
#   • Hardens .env for production
#   • Verifies Postgres is actually used (fails loudly if not)
#   • Migrates domain: sme.pritechmw.com → chumaflow.co
#   • Updates Nginx, SSL, restarts gunicorn-wms + daphne-wms
# =============================================================================

set -euo pipefail

# -------------------------------
# Configuration
# -------------------------------
readonly OLD_DOMAIN="sme.pritechmw.com"
readonly NEW_DOMAIN="chumaflow.co"
readonly NEW_DOMAIN_WWW="www.chumaflow.co"
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

check_root() {
    [[ $EUID -eq 0 ]] || error_exit "Run as root."
}

check_dependencies() {
    local missing=()
    for cmd in nginx certbot sed grep systemctl git curl python3 host; do
        command -v "$cmd" &>/dev/null || missing+=("$cmd")
    done
    [[ ${#missing[@]} -eq 0 ]] || error_exit "Missing: ${missing[*]}"
    log "Dependencies verified."
}

generate_unpinned_requirements() {
    local target="${1:-${PROJECT_DIR}/requirements.txt}"
    {
        echo "# ChumaFlow production dependencies (unpinned)."
        echo "# Regenerate: pip freeze | grep -vE '^(pip|setuptools|wheel)==' | sed -E 's/==.*//' | sort -u"
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
    log "Repo:  $GIT_REPO ($GIT_BRANCH)"
    log "=========================================="

    check_root
    check_dependencies

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

    [[ -f "${PROJECT_DIR}/requirements.txt" ]] && cp "${PROJECT_DIR}/requirements.txt" "${BACKUP_DIR}/requirements.txt.backup"
    [[ -f "${PROJECT_DIR}/db.sqlite3" ]]       && cp "${PROJECT_DIR}/db.sqlite3"       "${BACKUP_DIR}/db.sqlite3.backup"
    [[ -f "${PROJECT_DIR}/config/settings.py" ]] && cp "${PROJECT_DIR}/config/settings.py" "${BACKUP_DIR}/settings.py.backup"

    [[ -d "${PROJECT_DIR}/.git" ]] && git -C "$PROJECT_DIR" rev-parse HEAD > "${BACKUP_DIR}/git_head.txt" 2>/dev/null || true
    [[ -d "/etc/letsencrypt/live/${OLD_DOMAIN}" ]] && cp -r "/etc/letsencrypt/live/${OLD_DOMAIN}" "${BACKUP_DIR}/letsencrypt_${OLD_DOMAIN}" 2>/dev/null || true

    log "Backup complete."
}

# -------------------------------
# Git pull
# -------------------------------
pull_from_github() {
    [[ "$SKIP_GIT_PULL" == "1" ]] && { log "Skipping git pull."; return; }

    log "Pulling from GitHub..."
    cd "$PROJECT_DIR"

    if [[ ! -d ".git" ]]; then
        log "  Initializing git..."
        git init
        git remote add origin "$GIT_REPO"
        git fetch origin "$GIT_BRANCH"
        git checkout -B "$GIT_BRANCH" "origin/${GIT_BRANCH}"
    else
        local current
        current=$(git remote get-url origin 2>/dev/null || echo "")
        [[ "$current" != "$GIT_REPO" ]] && { git remote set-url origin "$GIT_REPO"; log "  Updated remote."; }
    fi

    git fetch origin "$GIT_BRANCH"
    git checkout "$GIT_BRANCH" 2>/dev/null || git checkout -b "$GIT_BRANCH" "origin/${GIT_BRANCH}"

    # Preserve .env across the reset
    cp "$ENV_FILE" "/tmp/chumaflow_env_${TIMESTAMP}.bak"
    git reset --hard "origin/${GIT_BRANCH}"
    [[ -f "$ENV_FILE" ]] || cp "/tmp/chumaflow_env_${TIMESTAMP}.bak" "$ENV_FILE"

    log "  HEAD: $(git rev-parse --short HEAD)"
}

# -------------------------------
# Sync requirements (unpinned)
# -------------------------------
sync_requirements() {
    [[ "$SKIP_REQUIREMENTS_SYNC" == "1" ]] && { log "Skipping requirements sync."; return; }

    log "Synchronizing Python dependencies (unpinned)..."
    cd "$PROJECT_DIR"
    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"

    if [[ -f "requirements.txt" ]] && grep -qE '==' requirements.txt; then
        log "  Detected pinned entries in current requirements.txt."
    fi

    echo
    echo "requirements.txt strategy:"
    echo "  [1] Write UNPINNED explicit list (recommended — no versions)"
    echo "  [2] Write UNPINNED pip-freeze of the entire venv"
    echo "  [3] Keep the file that came from git"
    read -rp "Choice [1/2/3] (default 1): " choice
    choice="${choice:-1}"

    case "$choice" in
        1)
            cp requirements.txt "requirements.txt.${TIMESTAMP}.bak" 2>/dev/null || true
            generate_unpinned_requirements "requirements.txt"
            log "  Wrote explicit unpinned requirements.txt (${#EXPLICIT_PACKAGES[@]} packages)."
            ;;
        2)
            cp requirements.txt "requirements.txt.${TIMESTAMP}.bak" 2>/dev/null || true
            {
                echo "# Auto-generated from venv (unpinned)."
                pip freeze | grep -v '^-e' | grep -vE '^(pip|setuptools|wheel)==' \
                    | sed -E 's/==.*//; s/ @ .*//' | sort -u
            } > requirements.txt
            log "  Wrote full unpinned pip-freeze."
            ;;
        3)
            log "  Keeping repo-provided requirements.txt."
            ;;
    esac

    if [[ -s requirements.txt ]]; then
        pip install --quiet --upgrade -r requirements.txt
    fi

    for pkg in gunicorn whitenoise channels channels_redis daphne redis; do
        python -c "import ${pkg}" 2>/dev/null || {
            log "  Installing missing runtime package: ${pkg}"
            pip install --quiet --upgrade "${pkg}"
        }
    done

    deactivate
    log "Dependency sync complete."
}

# -------------------------------
# .env production hardening
# -------------------------------
upsert_var() {
    local key="$1" val="$2"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        awk -v k="$key" -v v="$val" '
            BEGIN { FS="=" }
            $1==k { print k "=" v; next }
            { print }
        ' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

update_env_file() {
    log "Hardening .env for production..."

    # Core domain
    upsert_var "ALLOWED_HOSTS"        "${NEW_DOMAIN},${NEW_DOMAIN_WWW},${SERVER_IP},localhost,127.0.0.1"
    upsert_var "CSRF_TRUSTED_ORIGINS" "https://${NEW_DOMAIN},https://${NEW_DOMAIN_WWW}"
    upsert_var "BASE_URL"             "https://${NEW_DOMAIN}"

    # Production flags
    upsert_var "DEBUG"                          "False"
    upsert_var "SECURE_SSL_REDIRECT"            "True"
    upsert_var "SECURE_HSTS_SECONDS"            "31536000"
    upsert_var "SECURE_HSTS_INCLUDE_SUBDOMAINS" "True"
    upsert_var "SECURE_HSTS_PRELOAD"            "True"
    upsert_var "USE_REDIS"                      "True"

    # ---- Database ----
    # settings.py defaults to Postgres whenever DEBUG=False, so DB_ENGINE
    # is optional. We still write it for documentation / older settings.
    upsert_var "DB_ENGINE" "postgresql"

    # Verify Postgres credentials exist.
    local db_name db_user db_pass
    db_name=$(grep -E '^DB_NAME='     "$ENV_FILE" | cut -d= -f2- || true)
    db_user=$(grep -E '^DB_USER='     "$ENV_FILE" | cut -d= -f2- || true)
    db_pass=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
    if [[ -z "$db_name" || -z "$db_user" || -z "$db_pass" ]]; then
        log "  ERROR: Postgres credentials incomplete in .env."
        log "         DB_NAME='${db_name}' DB_USER='${db_user}' DB_PASSWORD=<hidden>"
        error_exit "Cannot proceed — Django will refuse to start."
    fi
    log "  Postgres credentials present (DB_NAME='${db_name}', DB_USER='${db_user}')."

    # Warn if a stray SQLite file exists.
    if [[ -f "${PROJECT_DIR}/db.sqlite3" ]]; then
        log "  WARNING: ${PROJECT_DIR}/db.sqlite3 exists."
        log "           If production data lives there, migrate it to Postgres"
        log "           before relying on the new configuration."
    fi

    # SECRET_KEY
    local current_key
    current_key=$(grep -E '^SECRET_KEY=' "$ENV_FILE" | cut -d= -f2- || true)
    if [[ "$current_key" == django-insecure-* ]]; then
        log "  SECRET_KEY is still the dev default."
        read -rp "  Generate a new production SECRET_KEY now? (y/N): " c
        if [[ "$c" =~ ^[Yy]$ ]]; then
            local new_key
            new_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(64))")
            upsert_var "SECRET_KEY" "$new_key"
            log "  New SECRET_KEY written."
        else
            log "  WARNING: leaving insecure SECRET_KEY."
        fi
    fi

    local email_host
    email_host=$(grep -E '^EMAIL_HOST=' "$ENV_FILE" | cut -d= -f2- || true)
    [[ "$email_host" == "mail.pritechmw.com" ]] && log "  NOTE: EMAIL_HOST still mail.pritechmw.com."

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

    log "  Verifying DB connection..."
    python - <<'PY' || error_exit "Django cannot connect to the configured database."
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection
engine = connection.settings_dict["ENGINE"]
name   = connection.settings_dict["NAME"]
print(f"    ENGINE = {engine}")
print(f"    NAME   = {name}")
if engine == "django.db.backends.sqlite3" and os.getenv("DEBUG", "").lower() in ("false", "0", "no"):
    raise SystemExit("Refusing: DEBUG is False but Django resolved to SQLite.")
connection.ensure_connection()
print("    Connection: OK")
PY

    log "  migrate..."
    python manage.py migrate --noinput

    log "  seed_plans..."
    python manage.py seed_plans 2>/dev/null || log "  (seed_plans not available — skipped)"

    log "  collectstatic..."
    python manage.py collectstatic --noinput --clear

    log "  check --deploy..."
    python manage.py check --deploy 2>&1 | tee -a "$LOG_FILE" || true

    deactivate
    log "Django setup complete."
}

# -------------------------------
# Nginx
# -------------------------------
update_nginx_config() {
    log "Updating Nginx..."
    sed -i.bak_nginx "s/${OLD_DOMAIN}/${NEW_DOMAIN}/g" "$NGINX_CONF"

    if ! grep -q "${NEW_DOMAIN_WWW}" "$NGINX_CONF"; then
        sed -i "s|server_name ${NEW_DOMAIN} ${SERVER_IP};|server_name ${NEW_DOMAIN} ${NEW_DOMAIN_WWW} ${SERVER_IP};|" "$NGINX_CONF"
    fi

    if nginx -t 2>/dev/null; then
        log "  Nginx config OK."
    else
        log "  Nginx config FAILED. Restoring backup."
        cp "${NGINX_CONF}.bak_nginx" "$NGINX_CONF"
        nginx -t
        error_exit "Nginx invalid — restored backup."
    fi
    systemctl reload nginx
    log "  Nginx reloaded."
}

# -------------------------------
# SSL
# -------------------------------
obtain_ssl_certificate() {
    log "Requesting SSL cert for ${NEW_DOMAIN}..."
    if certbot --nginx \
        -d "${NEW_DOMAIN}" \
        -d "${NEW_DOMAIN_WWW}" \
        --non-interactive --agree-tos --redirect 2>&1 | tee -a "$LOG_FILE"; then
        log "  SSL OK."
    else
        log "  WARNING: certbot failed. Run manually:"
        log "    sudo certbot --nginx -d ${NEW_DOMAIN} -d ${NEW_DOMAIN_WWW}"
    fi
    nginx -t 2>/dev/null && systemctl reload nginx || error_exit "Nginx invalid post-SSL."
}

# -------------------------------
# Restart services
# -------------------------------
restart_services() {
    log "Restarting services..."
    for svc in gunicorn-wms daphne-wms; do
        if systemctl list-unit-files | grep -q "^${svc}.service"; then
            systemctl restart "$svc"
            if systemctl is-active --quiet "$svc"; then
                log "  ${svc}: RUNNING"
            else
                systemctl status "$svc" --no-pager >> "$LOG_FILE" || true
                error_exit "${svc} failed to start."
            fi
        else
            log "  WARNING: ${svc}.service not found."
        fi
    done
}

# -------------------------------
# Verify
# -------------------------------
verify_migration() {
    log "Verifying..."
    for unit in nginx gunicorn-wms daphne-wms; do
        systemctl is-active --quiet "$unit" && log "  ${unit}: RUNNING" || log "  ${unit}: NOT RUNNING"
    done

    if curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | grep -q "HTTP"; then
        local code
        code=$(curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | awk '{print $2}')
        log "  https://${NEW_DOMAIN} → HTTP ${code}"
    else
        log "  https://${NEW_DOMAIN} → no response (DNS may still be propagating)"
    fi
}

# -------------------------------
# Summary
# -------------------------------
print_summary() {
    log "=========================================="
    log "DONE"
    log "=========================================="
    log "Commit:     $(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo n/a)"
    log "New domain: https://${NEW_DOMAIN}"
    log "Backup:     ${BACKUP_DIR}"
    log "Log:        ${LOG_FILE}"
    log ""
    log "Rollback:"
    log "  cp ${BACKUP_DIR}/nginx_sme.conf ${NGINX_CONF}"
    log "  cp ${BACKUP_DIR}/env.backup     ${ENV_FILE}"
    log "  cp ${BACKUP_DIR}/settings.py.backup ${PROJECT_DIR}/config/settings.py"
    log "  cp ${BACKUP_DIR}/requirements.txt.backup ${PROJECT_DIR}/requirements.txt"
    log "  cd ${PROJECT_DIR} && source venv/bin/activate && pip install -r requirements.txt"
    log "  nginx -t && systemctl reload nginx"
    log "  systemctl restart gunicorn-wms daphne-wms"
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