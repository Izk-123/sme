#!/bin/bash
# =============================================================================
# ChumaFlow Deployment & Domain Migration Script
#   • Pulls latest code from GitHub: https://github.com/Izk-123/sme.git
#   • Writes an UNPINNED requirements.txt (package names only, no versions)
#   • Hardens .env for production
#   • Verifies Postgres is actually used (fails loudly if not)
#   • Migrates domain: sme.pritechmw.com → chumaflow.pritechmw.com
#   • Updates Nginx, SSL, restarts the correct systemd services
#
# Server:   204.168.251.91
# Project:  /home/project/sme
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

# Allow explicit override:
#   sudo GUNICORN_SERVICE=gunicorn-sme DAPHNE_SERVICE=daphne-sme ./migrate_domain.sh
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

# Find a systemd service by prefix whose unit file references PROJECT_DIR.
find_service_for_project() {
    local prefix="$1"
    local dirname
    dirname=$(basename "$PROJECT_DIR")

    # 1. Unit file mentions the project directory
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

    # 2. Name matches <prefix>-<project basename>
    local candidate
    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-${dirname}\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    if [[ -n "$candidate" ]]; then
        echo "$candidate"
        return 0
    fi

    # 3. Last resort: first <prefix>-* service
    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-.*\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    if [[ -n "$candidate" ]]; then
        log "  WARNING: Could not find a ${prefix} service tied to ${PROJECT_DIR}."
        echo "$candidate"
        return 0
    fi

    return 1
}

detect_services() {
    if [[ -z "$GUNICORN_SERVICE" ]]; then
        GUNICORN_SERVICE=$(find_service_for_project gunicorn || true)
    fi
    if [[ -z "$DAPHNE_SERVICE" ]]; then
        DAPHNE_SERVICE=$(find_service_for_project daphne || true)
    fi
    [[ -z "$GUNICORN_SERVICE" ]] && GUNICORN_SERVICE="gunicorn-sme"
    [[ -z "$DAPHNE_SERVICE" ]]   && DAPHNE_SERVICE="daphne-sme"

    log "Services: GUNICORN=${GUNICORN_SERVICE}  DAPHNE=${DAPHNE_SERVICE}"

    # Warn if detected service doesn't reference the project
    local unit f
    for unit in "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        for f in /etc/systemd/system/${unit}.service \
                 /lib/systemd/system/${unit}.service \
                 /usr/lib/systemd/system/${unit}.service; do
            [[ -f "$f" ]] || continue
            if ! grep -q "${PROJECT_DIR}" "$f"; then
                log "  WARNING: ${unit}.service does not reference ${PROJECT_DIR}."
                log "           Override with: GUNICORN_SERVICE=... DAPHNE_SERVICE=... $0"
            fi
            break
        done
    done
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
        log "  WARNING: ${NEW_DOMAIN} does not resolve yet."
        log "           SSL via Certbot will likely FAIL until DNS propagates."
        read -rp "  Continue anyway? (y/N): " c
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

    # Preserve .env across hard reset (it's gitignored, but belt & braces)
    cp "$ENV_FILE" "/tmp/chumaflow_env_${TIMESTAMP}.bak"
    git reset --hard "origin/${GIT_BRANCH}"
    [[ -f "$ENV_FILE" ]] || cp "/tmp/chumaflow_env_${TIMESTAMP}.bak" "$ENV_FILE"

    log "  HEAD: $(git rev-parse --short HEAD)"
}

# -------------------------------
# Requirements sync (unpinned)
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
    echo "  [1] Write UNPINNED explicit list (recommended)"
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

    # Runtime-critical imports — install if missing
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

    local db_name db_user db_pass
    db_name=$(grep -E '^DB_NAME='     "$ENV_FILE" | cut -d= -f2- || true)
    db_user=$(grep -E '^DB_USER='     "$ENV_FILE" | cut -d= -f2- || true)
    db_pass=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
    if [[ -z "$db_name" || -z "$db_user" || -z "$db_pass" ]]; then
        error_exit "Postgres credentials incomplete in .env."
    fi
    log "  Postgres credentials present (DB_NAME='${db_name}')."

    if [[ -f "${PROJECT_DIR}/db.sqlite3" ]]; then
        log "  WARNING: db.sqlite3 exists — migrate data if it holds production records."
    fi

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
# Nginx — server_name only, cert paths left for Certbot
# -------------------------------
update_nginx_config() {
    log "Updating Nginx server_name (SSL cert paths will be handled by Certbot)..."

    # 1. Replace only the server_name directives that contain OLD_DOMAIN.
    #    Drops the IP fallback to avoid "conflicting server name" warnings.
    sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*${OLD_DOMAIN}[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"

    # 2. Replace OLD_DOMAIN → NEW_DOMAIN on any remaining lines EXCEPT
    #    ssl_certificate/ssl_certificate_key (Certbot rewrites those itself).
    awk -v old="$OLD_DOMAIN" -v new="$NEW_DOMAIN" '
        /ssl_certificate/ { print; next }
        { gsub(old, new); print }
    ' "$NGINX_CONF" > "${NGINX_CONF}.tmp" && mv "${NGINX_CONF}.tmp" "$NGINX_CONF"

    log "  --- Current server_name / host lines ---"
    grep -nE 'server_name|if \(\$host' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"

    # 3. Test — show stderr so real errors are visible.
    log "  Running 'nginx -t'..."
    if nginx -t 2>&1 | tee -a "$LOG_FILE" | grep -q "test is successful"; then
        log "  Nginx config OK (warnings about 204.168.251.91 are pre-existing, harmless)."
    else
        log "  Nginx config FAILED — restoring backup."
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        nginx -t 2>&1 | tee -a "$LOG_FILE" || true
        error_exit "Nginx invalid — restored from backup."
    fi

    systemctl reload nginx
    log "  Nginx reloaded."
}

# -------------------------------
# SSL — Certbot rewrites ssl_certificate paths itself
# -------------------------------
obtain_ssl_certificate() {
    log "Requesting SSL cert for ${NEW_DOMAIN} and ${NEW_DOMAIN_WWW}..."

    if certbot --nginx \
        -d "${NEW_DOMAIN}" -d "${NEW_DOMAIN_WWW}" \
        --non-interactive --agree-tos --redirect 2>&1 | tee -a "$LOG_FILE"; then
        log "  SSL OK."
    else
        log "  WARNING: Certbot failed for the www subdomain."
        log "           Retrying with just the main domain..."
        if certbot --nginx -d "${NEW_DOMAIN}" \
            --non-interactive --agree-tos --redirect 2>&1 | tee -a "$LOG_FILE"; then
            log "  SSL OK (main domain only)."
        else
            log "  WARNING: Certbot failed."
            log "           • If DNS hasn't propagated, retry later:"
            log "             sudo certbot --nginx -d ${NEW_DOMAIN}"
            log "           • Site remains reachable over HTTP meanwhile."
        fi
    fi

    if nginx -t 2>/dev/null; then
        systemctl reload nginx
    else
        log "  WARNING: Nginx config invalid after Certbot — leaving service as-is."
    fi
}

# -------------------------------
# Restart services
# -------------------------------
restart_services() {
    log "Restarting services..."
    for svc in "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        if systemctl list-unit-files | grep -q "^${svc}.service"; then
            systemctl restart "$svc"
            if systemctl is-active --quiet "$svc"; then
                log "  ${svc}: RUNNING"
            else
                systemctl status "$svc" --no-pager >> "$LOG_FILE" || true
                error_exit "${svc} failed to start."
            fi
        else
            log "  WARNING: ${svc}.service not found — skipping."
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
        local code
        code=$(curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | awk '{print $2}')
        log "  https://${NEW_DOMAIN} → HTTP ${code}"
    elif curl -sIk "http://${NEW_DOMAIN}" --max-time 10 | head -1 | grep -q "HTTP"; then
        log "  http://${NEW_DOMAIN} reachable (HTTPS not ready — run Certbot after DNS propagates)"
    else
        log "  ${NEW_DOMAIN} → no response (DNS may still be propagating)"
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
    log "Services:   ${GUNICORN_SERVICE}, ${DAPHNE_SERVICE}"
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
    log "  systemctl restart ${GUNICORN_SERVICE} ${DAPHNE_SERVICE}"
    log ""
    log "If HTTPS isn't working yet, run:"
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