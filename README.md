# ChumaFlow

> **Know your money. Grow your business.**
> Simple business software for Malawian SMEs.

ChumaFlow is a mobile-first, offline-friendly business operating system for small and medium businesses in Malawi. Record sales, track stock, collect debts, and see your real profit — from the phone in your pocket. No notebook. No guessing.

---

## Table of Contents

- [What It Is](#what-it-is)
- [The Problem](#the-problem)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Project Structure](#project-structure)
- [Modules](#modules)
- [Subscriptions & Payments](#subscriptions--payments)
- [Default Credentials](#default-credentials)
- [Deployment](#deployment)
- [Management Commands](#management-commands)
- [Testing](#testing)
- [Naming & Branding](#naming--branding)
- [Roadmap](#roadmap)
- [Credits](#credits)
- [License](#license)

---

## What It Is

ChumaFlow is a **modular, multi-tenant SaaS platform** designed for micro and small businesses in Malawi — the shops, stalls, and trade businesses that can't afford a traditional ERP (Odoo, QuickBooks, Sage) but have outgrown notebooks, WhatsApp, and memory.

Every business gets its own isolated workspace. Every employee logs in with their own account and sees only what their role allows. Every sale, expense, and stock movement is recorded, tracked, and reported — in plain language, not accounting jargon.

---

## The Problem

Most Malawian SMEs run on:
- 📒 Notebooks for sales
- 📱 WhatsApp for orders
- 🧮 Memory for customer debts
- 📦 Manual stock counting
- 🗃️ Shoeboxes of receipts

Result: **Lost revenue, leakages, no idea whether the business is actually profitable.** Traditional ERP is too expensive and assumes a desktop, accountant, and reliable internet.

ChumaFlow fixes that. Mobile-first, offline-tolerant, affordable, and built around how Malawian shops actually work.

---

## Features

### 🛒 Sales
- Record a sale in seconds
- Barcode scanning (camera or USB)
- Multiple payment methods: Cash, Airtel Money, TNM Mpamba, Bank, Card, Credit
- Credit sales with customer debt tracking
- Receipts — view, print, share on WhatsApp

### 📦 Inventory
- Real-time stock levels
- Low-stock alerts
- Stock movements (purchases, sales, adjustments, damaged, returns)
- Stock valuation report
- Barcode scanning and generation

### 👥 Customers
- Profiles, credit limits, outstanding balances
- Payment history
- Debt aging report
- Statements to share via WhatsApp

### 🚚 Suppliers
- Profiles, contact history, balances
- Purchase records and payment tracking

### 💰 Expenses
- Categories: rent, transport, salaries, packaging, etc.
- Monthly trends and comparisons
- Photo attachments for receipts

### 📊 Reports & Insights
- Business Overview (Sales, Expenses, Profit)
- Profit & Loss (PDF/Excel export)
- Sales Reports (by product, customer, employee, payment method)
- Expense Trends
- Inventory Reports
- Customer Debt Reports
- Top Products & Customers
- AI-style business insight summaries

### 👨‍💼 Team & Roles
- Owner, Cashier, Stock Clerk, Accountant
- Invite employees with a **shareable link** (no email server needed)
- Role-based access control
- Employee self-service portal (tasks, expense claims, requests, attendance)

### 💳 Subscriptions (SaaS)
- **Free** — 1 user, 10 products, 50 transactions/month
- **Starter** — MK10,000/month
- **Business** — MK25,000/month
- **Professional** — MK50,000/month
- 14-day free trial with full Business features
- Pay via Airtel Money, TNM Mpamba, Card, or Bank through **PayChangu**
- Grace period, read-only mode, reactivation — no data deletion

### 🔐 Security & Trust
- HTTPS everywhere
- Passwords hashed, secure sessions
- **Multi-tenant isolation** — you never see another business's data
- Audit trail (in progress)
- Daily automated backups

### 📱 Experience
- **Mobile-first PWA** — installable on Android, iOS, desktop
- **Offline-capable** (partial — sales queue for sync)
- **Dark / light mode**
- **Low-bandwidth** — HTMX, compressed assets, no heavy JS frameworks

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.2 |
| Frontend | Django Templates + Bootstrap 5 |
| Interactivity | HTMX |
| Real-time | Django Channels + Redis |
| Database | PostgreSQL (production) / SQLite (development) |
| Cache | Redis |
| Payments | PayChangu (with abstraction layer for future gateways) |
| PDF/Excel | ReportLab, openpyxl |
| Barcode | html5-qrcode |
| PWA | Service Worker + manifest.json |
| Deployment | Ubuntu VPS + Nginx + Gunicorn + Daphne |

---

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Izk-123/sme.git
cd sme
```

### 2. Create and activate a virtual environment

```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS / Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

Copy `.env.example` to `.env` and fill in your values (see [Environment Variables](#environment-variables)).

### 5. Run migrations

```bash
python manage.py migrate
```

### 6. Seed subscription plans and test data

```bash
python manage.py seed_plans
python manage.py seed --flush   # optional — creates demo org, users, products, sales
```

### 7. Start the server

```bash
python manage.py runserver
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000) — you'll land on the ChumaFlow landing page.

---

## Environment Variables

Create a `.env` file in the project root (next to `manage.py`):

```env
# ----------------------------------------------------------------------------
# Django
# ----------------------------------------------------------------------------
SECRET_KEY=your-long-random-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,yourdomain.com

# ----------------------------------------------------------------------------
# Database
# ----------------------------------------------------------------------------
# Development uses SQLite (leave these blank).
# For production, uncomment the PostgreSQL block in settings.py and set:
DB_NAME=chumaflow_db
DB_USER=chumaflow_user
DB_PASSWORD=your-strong-password
DB_HOST=localhost
DB_PORT=5432

# ----------------------------------------------------------------------------
# Redis (real-time notifications)
# ----------------------------------------------------------------------------
USE_REDIS=False          # True in production
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# ----------------------------------------------------------------------------
# Email (cPanel SMTP or any provider)
# ----------------------------------------------------------------------------
EMAIL_HOST=mail.yourdomain.com
EMAIL_PORT=587
EMAIL_USE_SSL=False
EMAIL_USE_TLS=True
EMAIL_HOST_USER=noreply@yourdomain.com
EMAIL_HOST_PASSWORD=your-email-password
DEFAULT_FROM_EMAIL=noreply@yourdomain.com

# ----------------------------------------------------------------------------
# URLs
# ----------------------------------------------------------------------------
BASE_URL=http://localhost:8000

# ----------------------------------------------------------------------------
# PayChangu (subscription payments)
# Get keys from dashboard.paychangu.com → Settings → API & Webhooks
# ----------------------------------------------------------------------------
PAYCHANGU_SECRET_KEY=sk_test_xxxxxxxxxxxx
PAYCHANGU_WEBHOOK_SECRET=whsec_xxxxxxxxxxxx
```

> ⚠️ **Never commit `.env` to git.** It's listed in `.gitignore`.

---

## Project Structure

```text
chumaflow/
│
├── config/                     # Project configuration
│   ├── settings.py             # Main settings (production)
│   ├── settings_dev.py         # Development settings (optional)
│   ├── urls.py                 # Root URL routing
│   ├── asgi.py                 # ASGI entrypoint (Channels/Daphne)
│   └── wsgi.py                 # WSGI entrypoint (Gunicorn)
│
├── accounts/                   # Authentication, profiles, roles, memberships, invitations
├── organizations/              # Multi-tenant Organization model
├── customers/                  # Customer profiles, payments, credit tracking
├── suppliers/                  # Supplier profiles and purchase history
├── sales/                      # Sales, products, inventory, barcodes, stock movements
├── expenses/                   # Expense tracking and categories
├── reports/                    # Reporting engine, PDF/Excel exports
├── subscriptions/              # Subscription plans, invoices, feature gating
├── payments/                   # Payment gateway integration (PayChangu)
├── core/                       # Dashboard, middleware, permissions, context processors
│
├── templates/                  # Global HTML templates
│   ├── base/
│   │   ├── base.html           # Authenticated layout (dashboard shell)
│   │   └── base_auth.html      # Public layout (login, signup, invitations)
│   ├── accounts/
│   ├── core/
│   ├── sales/
│   ├── reports/
│   ├── subscriptions/
│   └── landing.html            # Public landing page
│
├── static/                     # Global static files
│   ├── css/app.css
│   ├── js/app.js
│   ├── img/
│   └── icons/                  # PWA icons + favicon
│
├── media/                      # User uploads (profile photos, receipts)
├── manage.py
├── requirements.txt
├── README.md
└── .env                        # Not committed
```

---

## Modules

| Module | Purpose |
|--------|---------|
| `accounts` | User auth, profiles, roles, memberships, invitations, preferences |
| `organizations` | Multi-tenant business container |
| `customers` | Customer accounts, credit balances, payment tracking |
| `suppliers` | Supplier accounts, purchase history |
| `sales` | Sales transactions, products, inventory, stock movements |
| `expenses` | Business expenses and categories |
| `reports` | Business intelligence, PDF/Excel exports |
| `subscriptions` | SaaS plans, trial, lifecycle, feature gating |
| `payments` | PayChangu gateway integration and webhooks |
| `core` | Dashboard, middleware, permissions, shared mixins |

---

## Subscriptions & Payments

### Subscription lifecycle

```text
Trial → Active → Grace Period → Restricted → Reactivate
```

- Every new Organization gets a **14-day Business trial** automatically.
- After expiry, a **grace period** (5 days) allows continued access.
- After grace, the account switches to **read-only** — no new sales, but data stays intact and exportable.
- Reactivation is instant once payment is confirmed.

### Feature gating

Subscription features are checked via a service, not scattered `if` statements:

```python
from subscriptions.services import has_feature

if has_feature(request.organization, "barcode"):
    # allow barcode scanning
```

Frontend hides the button; **backend also enforces** the check.

### Payment flow (PayChangu)

```text
Owner picks plan
      ↓
payments/views.py → start_subscription_checkout()
      ↓
PayChangu hosted checkout (Airtel, Mpamba, card, bank)
      ↓
Customer pays
      ↓
PayChangu sends webhook → payments/views.py
      ↓
verify_and_apply() → server-side verification
      ↓
subscriptions/services.apply_gateway_payment()
      ↓
Subscription extended, Invoice created
```

**Never trust the browser.** Every payment is verified server-side with PayChangu before the subscription is touched.

### Setting up webhooks

1. In PayChangu dashboard, go to **Settings → API & Webhooks**
2. Set webhook URL to: `https://yourdomain.com/payments/webhooks/paychangu/`
3. Copy the **Webhook Secret** into `.env` as `PAYCHANGU_WEBHOOK_SECRET`
4. Enable **Receive Webhook Notifications**

See `PAYCHANGU_SETUP.md` for the detailed walkthrough.

---

## Default Credentials

After running `python manage.py seed --flush`, these users exist for testing:

| Role | Username | Password |
|------|----------|----------|
| Owner | `owner` | `password123` |
| Cashier | `cashier` | `password123` |
| Accountant | `accountant` | `password123` |

⚠️ **Never use these credentials in production.**

---

## Deployment

See the project's deployment notes for the full VPS walkthrough. The short version:

### 1. On the server

```bash
cd /home/project/chumaflow
source venv/bin/activate

git pull origin main
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
```

### 2. Restart services

```bash
sudo systemctl restart gunicorn-chumaflow
sudo systemctl restart daphne-chumaflow
sudo systemctl reload nginx
```

### 3. Systemd units

- `gunicorn-chumaflow.service` — WSGI HTTP server
- `daphne-chumaflow.service` — ASGI WebSocket server

Both point to `/home/project/chumaflow` and use `/home/project/chumaflow/venv/bin`.

### 4. Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name yourdomain.com;

    location /static/ { alias /home/project/chumaflow/staticfiles/; }
    location /media/  { alias /home/project/chumaflow/media/; }

    location / {
        include proxy_params;
        proxy_pass http://unix:/home/project/chumaflow/chumaflow.sock;
    }

    location /ws/ {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

### 5. SSL

```bash
sudo certbot --nginx -d yourdomain.com
```

---

## Management Commands

| Command | Purpose |
|---------|---------|
| `python manage.py seed_plans` | Seed default subscription plans (Free/Starter/Business/Professional) |
| `python manage.py seed --flush` | Seed demo org, users, products, sales, expenses (development only) |
| `python manage.py sweep_subscriptions` | Refresh subscription statuses, send renewal reminders — cron daily |

### Recommended cron

```cron
# Daily at 9am — refresh subscriptions and send reminders
0 9 * * * cd /home/project/chumaflow && venv/bin/python manage.py sweep_subscriptions >> /var/log/chumaflow_sweep.log 2>&1

# Daily at 2am — database backup
0 2 * * * pg_dump chumaflow_db | gzip > /backups/chumaflow_$(date +\%F).sql.gz
```

---

## Testing

```bash
# Run all tests
python manage.py test

# Run a specific app's tests
python manage.py test accounts
python manage.py test sales
python manage.py test subscriptions
```

Test coverage is currently light — critical paths (sales, payments, invitations) should be prioritized.

---

## Naming & Branding

**ChumaFlow** — from Chichewa *chuma* ("wealth") and the English *flow* ("movement").

**Tagline:** *Know your money. Grow your business.*

### Brand colors

| Role | Hex | Usage |
|------|-----|-------|
| Deep teal | `#0A2F35` | Headings, hero, footer |
| Flow teal | `#12A5A0` | "Flow" in name, logo background |
| Gold | `#F5B82E` | "Chuma" color, buttons, highlights |
| Mist | `#EEF6F5` | Soft section backgrounds |

### Logo

The mark is a teal rounded square with a gold letter **C** (for Chuma) and a white wave (for flow). Files live in `static/icons/`.

---

## Roadmap

### ✅ Done
- Authentication, profiles, memberships, roles
- Multi-tenant data isolation
- Sales, inventory, expenses, customers, suppliers
- Reports with PDF/Excel export
- Subscription plans and lifecycle
- PayChangu payment integration
- Employee self-service portal
- Real-time notifications (WebSocket)

### 🚧 In Progress
- Audit trail (who changed what, when)
- Sales returns and refunds
- Split payments (multiple payment methods per sale)
- Stocktaking with variance reports

### 📅 Planned
- Offline sales queue with background sync
- Multi-branch support
- Supplier purchase orders
- WhatsApp Business API integration
- SMS notifications
- Recurring/automated billing
- Localization (Chichewa)
- AI-powered business insights

### 💡 Future
- Working capital loans (partner with lenders)
- Inventory financing
- Business credit scoring
- Insurance partnerships
- Regional expansion (Zambia, Mozambique, Zimbabwe)

---

## Credits

**Built by** [Pritech ICT Solutions](https://pritechmw.com) — Blantyre, Malawi.

**Design inspiration:** NiceAdmin template by BootstrapMade (admin shell).

**Payment infrastructure:** [PayChangu](https://paychangu.com) — Malawian payment gateway supporting Airtel Money, TNM Mpamba, card, and bank.

**Icons:** Bootstrap Icons, Boxicons, Remix Icon.

**Fonts:** Bricolage Grotesque, DM Sans, Open Sans, Nunito, Poppins.

---

## License

This project is **proprietary software** owned by Pritech ICT Solutions. All rights reserved.

For commercial use, partnership, or licensing inquiries, contact: **[your-email@pritechmw.com]**

---

**ChumaFlow — Your business, organised. Your profit, visible.**