<<<<<<< HEAD
#!/bin/bash
# =============================================================================
# ChumaFlow Deployment & Domain Migration Script
#   • Migrates domain: sme.pritechmw.com → chumaflow.pritechmw.com
#   • Handles WhatsApp Business API environment variables
#   • Handles Google OAuth environment variables + allauth Site row
#   • Self-preserving across git pull
#
# Recommended:
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
# Largest upload nginx will accept. nginx defaults to 1M, which rejects ordinary phone photos
# with "413 Request Entity Too Large". Keep this a little ABOVE the limit enforced in Django forms.
readonly MAX_UPLOAD_SIZE="${MAX_UPLOAD_SIZE:-10M}"

readonly GIT_REPO="https://github.com/Izk-123/sme.git"
readonly GIT_BRANCH="main"

readonly LOG_FILE="/var/log/chumaflow_migration.log"
readonly TIMESTAMP=$(date +%Y%m%d_%H%M%S)
readonly BACKUP_DIR="/root/chumaflow_backup_${TIMESTAMP}"
readonly SELF_PATH="$(readlink -f "$0")"

# -----------------------------------------------------------------------------
# Canonical service names. These are what final_restart() will cycle at the
# end of every run, regardless of what auto-detection found. Detection is
# still used (in restart_services) so that a differently-named deployment
# gets its own units restarted too — but the canonical names are the ones
# that MUST come back up for the app to serve traffic.
# -----------------------------------------------------------------------------
readonly CANONICAL_GUNICORN="gunicorn-sme"
readonly CANONICAL_DAPHNE="daphne-sme"

GUNICORN_SERVICE="${GUNICORN_SERVICE:-}"
DAPHNE_SERVICE="${DAPHNE_SERVICE:-}"

# -----------------------------------------------------------------------------
# Runtime packages the app imports at boot. Missing any of these is a hard
# failure — INSTALLED_APPS references them and Django can't start without them.
#
# Updated for Google sign-in: django-allauth[socialaccount] is now required.
# The bracket form works fine inside pip's requirements file parser and as a
# quoted pip argument here.
# -----------------------------------------------------------------------------
readonly EXPLICIT_PACKAGES=(
    "Django" "channels" "channels-redis" "daphne" "reportlab"
    "openpyxl" "python-dotenv" "Pillow" "django-unfold" "psycopg2-binary"
    "gunicorn" "whitenoise" "redis" "requests" "twilio" "PyJWT" "aiohttp"
    "django-allauth[socialaccount]"
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
    log "Backup: ${BACKUP_DIR}"
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
    if [[ -n "$candidate" ]]; then
        echo "$candidate"; return 0
    fi

    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-.*\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    if [[ -n "$candidate" ]]; then
        log "  WARNING: no ${prefix} service tied to ${PROJECT_DIR}."
        echo "$candidate"; return 0
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
    [[ -z "$GUNICORN_SERVICE" ]] && GUNICORN_SERVICE="$CANONICAL_GUNICORN"
    [[ -z "$DAPHNE_SERVICE" ]]   && DAPHNE_SERVICE="$CANONICAL_DAPHNE"

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
        log "  WARNING: ${NEW_DOMAIN} does not resolve yet."
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

    [[ -f "${PROJECT_DIR}/requirements.txt" ]]   && cp "${PROJECT_DIR}/requirements.txt"   "${BACKUP_DIR}/requirements.txt.backup"
    [[ -f "${PROJECT_DIR}/db.sqlite3" ]]         && cp "${PROJECT_DIR}/db.sqlite3"         "${BACKUP_DIR}/db.sqlite3.backup"
    [[ -f "${PROJECT_DIR}/config/settings.py" ]] && cp "${PROJECT_DIR}/config/settings.py" "${BACKUP_DIR}/settings.py.backup"

    # PostgreSQL is the production database, so it must be backed up too.
    # Without this, `migrate` (and the data migrations) run with no way back.
    local pg_name pg_user pg_pass pg_host pg_port
    pg_name=$(grep -E '^DB_NAME='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_user=$(grep -E '^DB_USER='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_pass=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
    pg_host=$(grep -E '^DB_HOST='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_port=$(grep -E '^DB_PORT='     "$ENV_FILE" | cut -d= -f2- || true)
    if [[ -n "$pg_name" && -n "$pg_user" ]] && command -v pg_dump &>/dev/null; then
        if PGPASSWORD="$pg_pass" pg_dump -h "${pg_host:-localhost}" -p "${pg_port:-5432}" \
              -U "$pg_user" -Fc "$pg_name" > "${BACKUP_DIR}/postgres_${pg_name}.dump"; then
            log "  PostgreSQL dump saved."
        else
            error_exit "pg_dump failed. Refusing to continue without a database backup."
        fi
    else
        log "  WARNING: pg_dump not found or DB settings missing. No PostgreSQL backup was taken."
    fi
    chmod 700 "$BACKUP_DIR"   # the backup holds .env and database dumps

    [[ -d "${PROJECT_DIR}/.git" ]] && git -C "$PROJECT_DIR" rev-parse HEAD > "${BACKUP_DIR}/git_head.txt" 2>/dev/null || true

    log "Backup complete."
}

# -------------------------------
# Git pull (self-preserving)
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

    for pkg in gunicorn whitenoise channels channels_redis daphne redis allauth; do
        python -c "import ${pkg}" 2>/dev/null || {
            log "  Installing missing runtime package: ${pkg}"
            pip install --quiet --upgrade "${pkg}"
        }
    done

    deactivate
    log "Dependency sync complete."
}

# -------------------------------
# .env production hardening & WhatsApp + Google OAuth setup
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

    # --- Core Domain Settings ---
    upsert_var "ALLOWED_HOSTS"        "${NEW_DOMAIN},${NEW_DOMAIN_WWW},${SERVER_IP},localhost,127.0.0.1"
    upsert_var "CSRF_TRUSTED_ORIGINS" "https://${NEW_DOMAIN},https://${NEW_DOMAIN_WWW}"
    upsert_var "BASE_URL"             "https://${NEW_DOMAIN}"

    # --- Production Security & DB ---
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

    # --- SECRET_KEY Management ---
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

    # ==========================================================
    # WHATSAPP BUSINESS API SETUP
    # ==========================================================
    log "Checking WhatsApp Business API configuration..."

    local wa_phone wa_token wa_verify wa_secret
    wa_phone=$(grep -E '^WHATSAPP_PHONE_NUMBER_ID=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_token=$(grep -E '^WHATSAPP_ACCESS_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_verify=$(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_secret=$(grep -E '^WHATSAPP_APP_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)

    if [[ -z "$wa_phone" || -z "$wa_token" || -z "$wa_verify" || -z "$wa_secret" ]]; then
        log "  Some WhatsApp variables are missing."
        echo ""
        echo "  ──────────────────────────────────────────────────────────"
        echo "  WhatsApp Business API Setup"
        echo "  Get these values from: https://developers.facebook.com/apps/"
        echo "    → Your App → WhatsApp → Basic Setup"
        echo "    → Your App → App Settings → Basic (for App Secret)"
        echo "  ──────────────────────────────────────────────────────────"
        echo ""
        read -rp "  WHATSAPP_PHONE_NUMBER_ID (press Enter to keep current): " new_phone
        read -rsp "  WHATSAPP_ACCESS_TOKEN (hidden, Enter to keep current): " new_token; echo
        read -rp "  WHATSAPP_VERIFY_TOKEN (e.g., chumaflow_verify_2026): " new_verify
        read -rsp "  WHATSAPP_APP_SECRET (hidden, Enter to keep current): " new_secret; echo

        [[ -n "$new_phone" ]] && upsert_var "WHATSAPP_PHONE_NUMBER_ID" "$new_phone"
        [[ -n "$new_token" ]] && upsert_var "WHATSAPP_ACCESS_TOKEN" "$new_token"
        [[ -n "$new_verify" ]] && upsert_var "WHATSAPP_VERIFY_TOKEN" "$new_verify"
        [[ -n "$new_secret" ]] && upsert_var "WHATSAPP_APP_SECRET" "$new_secret"
        log "  WhatsApp variables updated."
    else
        log "  WhatsApp variables already present."
    fi

    # Print the Webhook URL for Meta configuration
    log ""
    log "  ════════════════════════════════════════════════════════════"
    log "  ACTION REQUIRED: Configure this Webhook URL in Meta"
    log "  URL:   https://${NEW_DOMAIN}/payments/webhooks/whatsapp/"
    log "  Token: $(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || echo 'Not set')"
    log "  ════════════════════════════════════════════════════════════"
    log ""

    # ==========================================================
    # GOOGLE OAUTH SETUP  (django-allauth)
    # ==========================================================
    #
    # django-allauth needs two credentials to talk to Google: an OAuth
    # 2.0 Client ID and its secret, created at
    # console.cloud.google.com → APIs & Services → Credentials.
    #
    # The redirect URI registered on the Google side MUST match the
    # domain allauth builds it from — which is the Site row in the
    # database, updated during `django_setup` below. If you change the
    # domain here but forget to update the Site row (or vice versa),
    # Google will refuse the callback with `redirect_uri_mismatch`.
    #
    log "Checking Google OAuth configuration..."

    local g_client g_secret
    g_client=$(grep -E '^GOOGLE_OAUTH_CLIENT_ID='     "$ENV_FILE" | cut -d= -f2- || true)
    g_secret=$(grep -E '^GOOGLE_OAUTH_CLIENT_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)

    if [[ -z "$g_client" || -z "$g_secret" ]]; then
        log "  Google OAuth credentials missing."
        echo ""
        echo "  ──────────────────────────────────────────────────────────"
        echo "  Google OAuth Setup (for 'Continue with Google')"
        echo "  Get these values from: https://console.cloud.google.com/"
        echo "    → APIs & Services → Credentials"
        echo "    → OAuth 2.0 Client IDs → your Web application"
        echo "  ──────────────────────────────────────────────────────────"
        echo ""
        read -rp "  GOOGLE_OAUTH_CLIENT_ID (Enter to keep current): " new_g_client
        read -rsp "  GOOGLE_OAUTH_CLIENT_SECRET (hidden, Enter to keep current): " new_g_secret; echo

        [[ -n "$new_g_client" ]] && upsert_var "GOOGLE_OAUTH_CLIENT_ID"     "$new_g_client"
        [[ -n "$new_g_secret" ]] && upsert_var "GOOGLE_OAUTH_CLIENT_SECRET" "$new_g_secret"
        log "  Google OAuth variables updated."
    else
        log "  Google OAuth variables already present."
    fi

    # Show the callback URL the operator must register on the Google side.
    log ""
    log "  ════════════════════════════════════════════════════════════"
    log "  ACTION REQUIRED: Register this callback URL in Google Cloud"
    log "  https://${NEW_DOMAIN}/accounts/google/login/callback/"
    log "  https://${NEW_DOMAIN_WWW}/accounts/google/login/callback/  (if using www)"
    log "  ════════════════════════════════════════════════════════════"
    log ""

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

    # -----------------------------------------------------------------
    # Update the allauth Site row so OAuth callback URLs point at the
    # new domain. django.contrib.sites stores one Site row (typically
    # pk=1) whose `domain` field is what allauth uses to build every
    # provider callback URL.
    #
    # If this step is skipped, the Site row still says `example.com`
    # and Google rejects every callback with redirect_uri_mismatch,
    # even though everything else looks correct.
    #
    # The step is idempotent: running it twice just writes the same
    # value.
    # -----------------------------------------------------------------
    log "  Updating allauth Site row to match new domain..."
    python - <<'PY' || log "  WARNING: Could not update Site row. Google sign-in may break."
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.conf import settings
from django.contrib.sites.models import Site

base = getattr(settings, "BASE_URL", "") or ""
domain = base.replace("https://", "").replace("http://", "").rstrip("/")
if not domain:
    print("    BASE_URL not set; skipping Site update.")
else:
    site, created = Site.objects.get_or_create(pk=settings.SITE_ID)
    previous = site.domain
    site.domain = domain
    site.name = "ChumaFlow"
    site.save()
    action = "created" if created else "updated"
    print(f"    Site row {action}: {previous!r} → {domain!r}")

    count = Site.objects.count()
    print(f"    Site rows total: {count}")
PY

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
# Nginx (fixed sed — no delimiter collision)
# -------------------------------
ensure_upload_limit() {
    log "  Setting client_max_body_size ${MAX_UPLOAD_SIZE}..."
    if grep -qE '^[[:space:]]*client_max_body_size' "$NGINX_CONF"; then
        # already present: just update the value (avoids a "duplicate directive" error)
        sed -i -E "s|^([[:space:]]*client_max_body_size[[:space:]]+)[^;]*;|\\1${MAX_UPLOAD_SIZE};|" "$NGINX_CONF"
    else
        # add it right after each server_name line
        sed -i -E "s|^([[:space:]]*)(server_name[[:space:]]+[^;]*;)|\\1\\2\n\\1client_max_body_size ${MAX_UPLOAD_SIZE};|" "$NGINX_CONF"
    fi
    grep -n 'client_max_body_size' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"
}

update_nginx_config() {
    log "Updating Nginx server_name (SSL cert paths will be handled by Certbot)..."

    # Substitution 1: any server_name line containing sme.pritechmw.com
    if ! sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*sme\.pritechmw\.com[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"; then
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        error_exit "sed failed updating server_name (sme)."
    fi

    # Substitution 2: any server_name line containing chumaflow.co
    if ! sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*chumaflow\.co[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"; then
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        error_exit "sed failed updating server_name (chumaflow.co)."
    fi

    # Replace remaining old-domain refs, EXCEPT ssl_certificate* lines
    awk -v old1="sme.pritechmw.com" -v old2="chumaflow.co" -v new="$NEW_DOMAIN" '
        /ssl_certificate/ { print; next }
        { gsub(old1, new); gsub(old2, new); print }
    ' "$NGINX_CONF" > "${NGINX_CONF}.tmp" && mv "${NGINX_CONF}.tmp" "$NGINX_CONF"

    ensure_upload_limit

    log "  --- Current server_name / host lines ---"
    grep -nE 'server_name|if \(\$host' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"

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
# SSL
# -------------------------------
obtain_ssl_certificate() {
    log "Requesting SSL cert for ${NEW_DOMAIN} and ${NEW_DOMAIN_WWW}..."

    if certbot --nginx \
        -d "${NEW_DOMAIN}" -d "${NEW_DOMAIN_WWW}" \
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

    if nginx -t 2>/dev/null; then
        systemctl reload nginx
    else
        log "  WARNING: Nginx config invalid after Certbot — leaving service as-is."
    fi
}

# -------------------------------
# Restart services
# -------------------------------
service_exists() {
    systemctl cat "$1" &>/dev/null
}

restart_services() {
    log "Restarting services..."
    for svc in "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        if service_exists "$svc"; then
            systemctl restart "$svc"
            if systemctl is-active --quiet "$svc"; then
                log "  ${svc}: RUNNING"
            else
                systemctl status "$svc" --no-pager >> "$LOG_FILE" || true
                error_exit "${svc} failed to start."
            fi
        else
            log "  WARNING: ${svc} not found as a systemd unit — skipping."
        fi
    done
}

# -----------------------------------------------------------------------------
# Final restart — always runs, always targets the canonical service names.
#
# Restart_services() above cycles whatever units auto-detection found, which
# is correct for a differently-named deployment but leaves a gap: if the
# detection picks a NON-canonical name (e.g. gunicorn-sme-prod) and the
# canonical gunicorn-sme / daphne-sme units are also present, only the
# detected ones get cycled here. This function closes that gap by running
# the canonical commands unconditionally at the end of every run.
#
# Failures are tolerated (logged, not fatal) because the script is
# idempotent and the summary that follows is more useful than a silent
# abort. A genuinely broken unit will show up in verify_migration()'s
# systemctl is-active checks just above.
# -----------------------------------------------------------------------------
final_restart() {
    log "──────────────────────────────────────────"
    log "Final restart — cycling canonical services"
    log "──────────────────────────────────────────"

    # Two loops because we want a distinct outcome logged for each step
    # and we want the nginx reload to happen regardless of whether either
    # restart succeeded.
    if systemctl restart "$CANONICAL_GUNICORN" 2>>"$LOG_FILE"; then
        log "  systemctl restart ${CANONICAL_GUNICORN}: OK"
    else
        log "  systemctl restart ${CANONICAL_GUNICORN}: FAILED (see log)"
    fi

    if systemctl restart "$CANONICAL_DAPHNE" 2>>"$LOG_FILE"; then
        log "  systemctl restart ${CANONICAL_DAPHNE}: OK"
    else
        log "  systemctl restart ${CANONICAL_DAPHNE}: FAILED (see log)"
    fi

    if systemctl reload nginx 2>>"$LOG_FILE"; then
        log "  systemctl reload nginx: OK"
    else
        log "  systemctl reload nginx: FAILED (see log)"
    fi

    log "Final restart complete."
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
        log "  http://${NEW_DOMAIN} reachable (HTTPS pending Certbot)"
    else
        log "  ${NEW_DOMAIN} → no response"
    fi

    # ==========================================================
    # VERIFY WHATSAPP WEBHOOK ENDPOINT
    # ==========================================================
    log "  Verifying WhatsApp webhook endpoint..."
    local wa_code
    wa_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://${NEW_DOMAIN}/payments/webhooks/whatsapp/" \
        --max-time 10 || echo "000")

    if [[ "$wa_code" == "403" || "$wa_code" == "400" || "$wa_code" == "200" ]]; then
        log "  WhatsApp webhook is LIVE (HTTP ${wa_code})."
    else
        log "  WARNING: WhatsApp webhook returned HTTP ${wa_code}. Check your URLs."
    fi

    # ==========================================================
    # VERIFY GOOGLE SIGN-IN ENDPOINT
    # ==========================================================
    log "  Verifying Google sign-in endpoint..."
    local g_code g_location
    g_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://${NEW_DOMAIN}/accounts/google/login/" \
        --max-time 10 || echo "000")

    if [[ "$g_code" == "302" ]]; then
        g_location=$(curl -sI "https://${NEW_DOMAIN}/accounts/google/login/" \
            --max-time 10 | grep -i '^location:' | head -1 || true)
        if echo "$g_location" | grep -q "accounts.google.com"; then
            log "  Google sign-in endpoint is LIVE (302 → accounts.google.com)."
        else
            log "  Google sign-in redirected somewhere unexpected: ${g_location}"
        fi
    elif [[ "$g_code" == "500" ]]; then
        log "  ERROR: Google sign-in returned HTTP 500 — provider likely misconfigured."
        log "  Check that GOOGLE_OAUTH_CLIENT_ID is set and the Site row is correct."
    else
        log "  WARNING: Google sign-in endpoint returned HTTP ${g_code}."
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
    log "Log:        ${LOG_FILE}"
    log ""
    log "Rollback:"
    log "  cp ${BACKUP_DIR}/nginx_sme.conf ${NGINX_CONF}"
    log "  cp ${BACKUP_DIR}/env.backup     ${ENV_FILE}"
    log "  nginx -t && systemctl reload nginx"
    log "  systemctl restart ${GUNICORN_SERVICE} ${DAPHNE_SERVICE}"
    log ""
    log "If HTTPS isn't working:"
    log "  sudo certbot --nginx -d ${NEW_DOMAIN} -d ${NEW_DOMAIN_WWW}"
    log ""
    log "════════════════════════════════════════════════════════════"
    log "NEXT STEP 1: Configure this Webhook in Meta"
    log "1. Go to developers.facebook.com -> Your App -> WhatsApp -> Configuration"
    log "2. Callback URL: https://${NEW_DOMAIN}/payments/webhooks/whatsapp/"
    log "3. Verify Token: $(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || echo 'Not set')"
    log "════════════════════════════════════════════════════════════"
    log "NEXT STEP 2: Register the Google OAuth callback URL"
    log "1. Go to console.cloud.google.com -> APIs & Services -> Credentials"
    log "2. Edit your OAuth 2.0 Client ID (Web application)"
    log "3. Under 'Authorized redirect URIs', add:"
    log "     https://${NEW_DOMAIN}/accounts/google/login/callback/"
    log "     https://${NEW_DOMAIN_WWW}/accounts/google/login/callback/  (if using www)"
    log "4. Also add to 'Authorized JavaScript origins':"
    log "     https://${NEW_DOMAIN}"
    log "     https://${NEW_DOMAIN_WWW}"
    log "5. Save. Google changes propagate immediately."
    log "════════════════════════════════════════════════════════════"
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
    final_restart
    print_summary
}

=======
#!/bin/bash
# =============================================================================
# ChumaFlow Deployment & Domain Migration Script
#   • Migrates domain: sme.pritechmw.com → chumaflow.pritechmw.com
#   • Handles WhatsApp Business API environment variables
#   • Self-preserving across git pull
#
# Recommended:
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
# Largest upload nginx will accept. nginx defaults to 1M, which rejects ordinary phone photos
# with "413 Request Entity Too Large". Keep this a little ABOVE the limit enforced in Django forms.
readonly MAX_UPLOAD_SIZE="${MAX_UPLOAD_SIZE:-10M}"

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
    log "Backup: ${BACKUP_DIR}"
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
    if [[ -n "$candidate" ]]; then
        echo "$candidate"; return 0
    fi

    candidate=$(systemctl list-unit-files --type=service --no-legend 2>/dev/null \
        | awk '{print $1}' | grep -E "^${prefix}-.*\.service$" | head -1 \
        | sed 's/\.service$//' || true)
    if [[ -n "$candidate" ]]; then
        log "  WARNING: no ${prefix} service tied to ${PROJECT_DIR}."
        echo "$candidate"; return 0
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
        log "  WARNING: ${NEW_DOMAIN} does not resolve yet."
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

    [[ -f "${PROJECT_DIR}/requirements.txt" ]]   && cp "${PROJECT_DIR}/requirements.txt"   "${BACKUP_DIR}/requirements.txt.backup"
    [[ -f "${PROJECT_DIR}/db.sqlite3" ]]         && cp "${PROJECT_DIR}/db.sqlite3"         "${BACKUP_DIR}/db.sqlite3.backup"
    [[ -f "${PROJECT_DIR}/config/settings.py" ]] && cp "${PROJECT_DIR}/config/settings.py" "${BACKUP_DIR}/settings.py.backup"
    # PostgreSQL is the production database, so it must be backed up too.
    # Without this, `migrate` (and the data migrations) run with no way back.
    local pg_name pg_user pg_pass pg_host pg_port
    pg_name=$(grep -E '^DB_NAME='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_user=$(grep -E '^DB_USER='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_pass=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2- || true)
    pg_host=$(grep -E '^DB_HOST='     "$ENV_FILE" | cut -d= -f2- || true)
    pg_port=$(grep -E '^DB_PORT='     "$ENV_FILE" | cut -d= -f2- || true)
    if [[ -n "$pg_name" && -n "$pg_user" ]] && command -v pg_dump &>/dev/null; then
        if PGPASSWORD="$pg_pass" pg_dump -h "${pg_host:-localhost}" -p "${pg_port:-5432}" \
              -U "$pg_user" -Fc "$pg_name" > "${BACKUP_DIR}/postgres_${pg_name}.dump"; then
            log "  PostgreSQL dump saved."
        else
            error_exit "pg_dump failed. Refusing to continue without a database backup."
        fi
    else
        log "  WARNING: pg_dump not found or DB settings missing. No PostgreSQL backup was taken."
    fi
    chmod 700 "$BACKUP_DIR"   # the backup holds .env and database dumps

    [[ -d "${PROJECT_DIR}/.git" ]] && git -C "$PROJECT_DIR" rev-parse HEAD > "${BACKUP_DIR}/git_head.txt" 2>/dev/null || true

    log "Backup complete."
}

# -------------------------------
# Git pull (self-preserving)
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
# .env production hardening & WhatsApp Setup
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

    # --- Core Domain Settings ---
    upsert_var "ALLOWED_HOSTS"        "${NEW_DOMAIN},${NEW_DOMAIN_WWW},${SERVER_IP},localhost,127.0.0.1"
    upsert_var "CSRF_TRUSTED_ORIGINS" "https://${NEW_DOMAIN},https://${NEW_DOMAIN_WWW}"
    upsert_var "BASE_URL"             "https://${NEW_DOMAIN}"

    # --- Production Security & DB ---
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

    # --- SECRET_KEY Management ---
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

    # ==========================================================
    # WHATSAPP BUSINESS API SETUP
    # ==========================================================
    log "Checking WhatsApp Business API configuration..."
    
    local wa_phone wa_token wa_verify wa_secret
    wa_phone=$(grep -E '^WHATSAPP_PHONE_NUMBER_ID=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_token=$(grep -E '^WHATSAPP_ACCESS_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_verify=$(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || true)
    wa_secret=$(grep -E '^WHATSAPP_APP_SECRET=' "$ENV_FILE" | cut -d= -f2- || true)

    if [[ -z "$wa_phone" || -z "$wa_token" || -z "$wa_verify" || -z "$wa_secret" ]]; then
        log "  Some WhatsApp variables are missing."
        echo ""
        echo "  ──────────────────────────────────────────────────────────"
        echo "  WhatsApp Business API Setup"
        echo "  Get these values from: https://developers.facebook.com/apps/"
        echo "    → Your App → WhatsApp → Basic Setup"
        echo "    → Your App → App Settings → Basic (for App Secret)"
        echo "  ──────────────────────────────────────────────────────────"
        echo ""
        read -rp "  WHATSAPP_PHONE_NUMBER_ID (press Enter to keep current): " new_phone
        read -rsp "  WHATSAPP_ACCESS_TOKEN (hidden, Enter to keep current): " new_token; echo
        read -rp "  WHATSAPP_VERIFY_TOKEN (e.g., chumaflow_verify_2026): " new_verify
        read -rsp "  WHATSAPP_APP_SECRET (hidden, Enter to keep current): " new_secret; echo

        [[ -n "$new_phone" ]] && upsert_var "WHATSAPP_PHONE_NUMBER_ID" "$new_phone"
        [[ -n "$new_token" ]] && upsert_var "WHATSAPP_ACCESS_TOKEN" "$new_token"
        [[ -n "$new_verify" ]] && upsert_var "WHATSAPP_VERIFY_TOKEN" "$new_verify"
        [[ -n "$new_secret" ]] && upsert_var "WHATSAPP_APP_SECRET" "$new_secret"
        log "  WhatsApp variables updated."
    else
        log "  WhatsApp variables already present."
    fi

    # Print the Webhook URL for Meta configuration
    log ""
    log "  ════════════════════════════════════════════════════════════"
    log "  ACTION REQUIRED: Configure this Webhook URL in Meta"
    log "  URL:   https://${NEW_DOMAIN}/payments/webhooks/whatsapp/"
    log "  Token: $(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || echo 'Not set')"
    log "  ════════════════════════════════════════════════════════════"
    log ""

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
# Nginx (fixed sed — no delimiter collision)
# -------------------------------
ensure_upload_limit() {
    log "  Setting client_max_body_size ${MAX_UPLOAD_SIZE}..."
    if grep -qE '^[[:space:]]*client_max_body_size' "$NGINX_CONF"; then
        # already present: just update the value (avoids a "duplicate directive" error)
        sed -i -E "s|^([[:space:]]*client_max_body_size[[:space:]]+)[^;]*;|\\1${MAX_UPLOAD_SIZE};|" "$NGINX_CONF"
    else
        # add it right after each server_name line
        sed -i -E "s|^([[:space:]]*)(server_name[[:space:]]+[^;]*;)|\\1\\2\n\\1client_max_body_size ${MAX_UPLOAD_SIZE};|" "$NGINX_CONF"
    fi
    grep -n 'client_max_body_size' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"
}

update_nginx_config() {
    log "Updating Nginx server_name (SSL cert paths will be handled by Certbot)..."

    # Substitution 1: any server_name line containing sme.pritechmw.com
    if ! sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*sme\.pritechmw\.com[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"; then
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        error_exit "sed failed updating server_name (sme)."
    fi

    # Substitution 2: any server_name line containing chumaflow.co
    if ! sed -i -E \
        "s|(server_name[[:space:]]+)[^;]*chumaflow\.co[^;]*;|\1${NEW_DOMAIN} ${NEW_DOMAIN_WWW};|g" \
        "$NGINX_CONF"; then
        cp "${BACKUP_DIR}/nginx_sme.conf" "$NGINX_CONF"
        error_exit "sed failed updating server_name (chumaflow.co)."
    fi

    # Replace remaining old-domain refs, EXCEPT ssl_certificate* lines
    awk -v old1="sme.pritechmw.com" -v old2="chumaflow.co" -v new="$NEW_DOMAIN" '
        /ssl_certificate/ { print; next }
        { gsub(old1, new); gsub(old2, new); print }
    ' "$NGINX_CONF" > "${NGINX_CONF}.tmp" && mv "${NGINX_CONF}.tmp" "$NGINX_CONF"

    ensure_upload_limit

    log "  --- Current server_name / host lines ---"
    grep -nE 'server_name|if \(\$host' "$NGINX_CONF" | sed 's/^/    /' | tee -a "$LOG_FILE"

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
# SSL
# -------------------------------
obtain_ssl_certificate() {
    log "Requesting SSL cert for ${NEW_DOMAIN} and ${NEW_DOMAIN_WWW}..."

    if certbot --nginx \
        -d "${NEW_DOMAIN}" -d "${NEW_DOMAIN_WWW}" \
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

    if nginx -t 2>/dev/null; then
        systemctl reload nginx
    else
        log "  WARNING: Nginx config invalid after Certbot — leaving service as-is."
    fi
}

# -------------------------------
# Restart services
# -------------------------------
service_exists() {
    systemctl cat "$1" &>/dev/null
}

restart_services() {
    log "Restarting services..."
    for svc in "$GUNICORN_SERVICE" "$DAPHNE_SERVICE"; do
        if service_exists "$svc"; then
            systemctl restart "$svc"
            if systemctl is-active --quiet "$svc"; then
                log "  ${svc}: RUNNING"
            else
                systemctl status "$svc" --no-pager >> "$LOG_FILE" || true
                error_exit "${svc} failed to start."
            fi
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
        local code
        code=$(curl -sIk "https://${NEW_DOMAIN}" --max-time 10 | head -1 | awk '{print $2}')
        log "  https://${NEW_DOMAIN} → HTTP ${code}"
    elif curl -sIk "http://${NEW_DOMAIN}" --max-time 10 | head -1 | grep -q "HTTP"; then
        log "  http://${NEW_DOMAIN} reachable (HTTPS pending Certbot)"
    else
        log "  ${NEW_DOMAIN} → no response"
    fi

    # ==========================================================
    # VERIFY WHATSAPP WEBHOOK ENDPOINT
    # ==========================================================
    log "  Verifying WhatsApp webhook endpoint..."
    local wa_code
    wa_code=$(curl -s -o /dev/null -w "%{http_code}" \
        "https://${NEW_DOMAIN}/payments/webhooks/whatsapp/" \
        --max-time 10 || echo "000")
    
    if [[ "$wa_code" == "403" || "$wa_code" == "400" || "$wa_code" == "200" ]]; then
        log "  WhatsApp webhook is LIVE (HTTP ${wa_code})."
    else
        log "  WARNING: WhatsApp webhook returned HTTP ${wa_code}. Check your URLs."
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
    log "Log:        ${LOG_FILE}"
    log ""
    log "Rollback:"
    log "  cp ${BACKUP_DIR}/nginx_sme.conf ${NGINX_CONF}"
    log "  cp ${BACKUP_DIR}/env.backup     ${ENV_FILE}"
    log "  nginx -t && systemctl reload nginx"
    log "  systemctl restart ${GUNICORN_SERVICE} ${DAPHNE_SERVICE}"
    log ""
    log "If HTTPS isn't working:"
    log "  sudo certbot --nginx -d ${NEW_DOMAIN} -d ${NEW_DOMAIN_WWW}"
    log ""
    log "════════════════════════════════════════════════════════════"
    log "NEXT STEP: Configure this Webhook in Meta"
    log "1. Go to developers.facebook.com -> Your App -> WhatsApp -> Configuration"
    log "2. Callback URL: https://${NEW_DOMAIN}/payments/webhooks/whatsapp/"
    log "3. Verify Token: $(grep -E '^WHATSAPP_VERIFY_TOKEN=' "$ENV_FILE" | cut -d= -f2- || echo 'Not set')"
    log "════════════════════════════════════════════════════════════"
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

>>>>>>> e3b67a5 (new files)
main "$@"