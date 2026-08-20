```markdown
# 🏢 SME Business OS

Multi-tenant Django platform for Malawian SMEs: sales, inventory, expenses, customers, suppliers, reports. Mobile-first PWA with barcode scanning, real-time notifications, role-based access, offline sync, PDF/Excel exports. Turn data into insights—no ERP complexity, just decision support.

---

## 📌 Repository

```bash
git clone https://github.com/Izk-123/sme.git
```

---

## ✨ Key Features

- **Multi-Tenant Architecture**: Single user can manage multiple businesses (Organizations) with distinct Roles and Memberships.
- **Sales Management**: Quick, mobile-friendly sales form with live HTMX total calculation and dynamic item rows.
- **Inventory Control**: Track stock levels, receive new stock from suppliers, automated low-stock alerts, and real-time stock valuations.
- **Expense Tracking**: Categorize and monitor expenses with detailed trend reports.
- **Customer & Supplier Management**: Track outstanding balances, payment histories, and credit sales.
- **Reporting & Analytics**: Dedicated reports hub providing actionable insights, including Profit & Loss, Sales Reports, Expense Trends, Business Overview, Inventory Stock, and Customer Debt.
- **Export Capabilities**: Download professional PDF reports (ReportLab) and Excel spreadsheets (openpyxl) with one click.
- **Barcode Scanning**: Support for camera scanning (html5-qrcode) and USB barcode readers to speed up sales and receiving stock.
- **Real-Time Notifications**: WebSocket-powered in-app alerts for sales and critical events.
- **Dynamic Currency**: Automatically formats monetary values based on the organization's selected currency (e.g., MWK).
- **Progressive Web App (PWA)**: Caches static assets via a Service Worker for fast loading and basic offline capabilities.
- **Responsive UI**: Mobile-first design using Bootstrap 5 and HTMX for a seamless experience on phones, tablets, and desktops.

---

## 🛠️ Tech Stack

- **Backend**: Python, Django 5.2, Django Channels
- **Database**: SQLite (development) / PostgreSQL (production)
- **Real-time / Cache**: Redis (production) / In-Memory (development)
- **Frontend**: Django Templates, Bootstrap 5, HTMX, Alpine.js (minor), ApexCharts & ECharts
- **PWA**: Service Worker, `manifest.json`
- **Export**: ReportLab (PDF), openpyxl (Excel)
- **Barcode**: html5-qrcode

---

## 🚀 Quick Start

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

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

*(If you don't have a `requirements.txt`, install manually: `pip install django channels channels-redis reportlab openpyxl python-dotenv`)*

### 4. Configure Environment Variables
Create a `.env` file in the project root (next to `manage.py`) with the following:

```env
SECRET_KEY=django-insecure-your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
EMAIL_HOST=mail.yourdomain.com
EMAIL_PORT=465
EMAIL_USE_SSL=True
EMAIL_HOST_USER=noreply@pritechmw.com
EMAIL_HOST_PASSWORD=your-password
BASE_URL=http://localhost:8000
USE_REDIS=False
```

### 5. Run Migrations & Seed Database
```bash
python manage.py migrate
python manage.py seed --flush
```

### 6. Start the Development Server
```bash
python manage.py runserver
```

---

## 🔐 Default Login Credentials

After seeding the database (`python manage.py seed --flush`), you can log in with the following users:

| Role        | Username    | Password      |
|-------------|-------------|---------------|
| **Owner**   | `owner`     | `password123` |
| **Cashier** | `cashier`   | `password123` |
| **Accountant** | `accountant` | `password123` |

---

## 📁 Project Structure

```text
sme/
├── config/                 # Project settings, URLs, ASGI/WSGI
├── accounts/               # User Auth, Profiles, Memberships, Roles
├── core/                   # Dashboard, Middleware, Permissions, Context Processors
├── sales/                  # Sales, Products, Inventory, Barcode
├── expenses/               # Expenses & Expense Categories
├── customers/              # Customer profiles & Payments
├── suppliers/              # Supplier profiles
├── reports/                # Reporting engine, services, exports
├── organizations/          # Multi-tenant Organization model
├── notifications/          # Real-time notifications model & consumers
├── static/                 # Global static files (CSS, JS, Images)
├── templates/              # Global HTML templates
├── manage.py
└── .env                    # Environment variables (ignored by git)
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙌 Credits

Designed and built by [Pritech](http://pritechmw.com/).  
Based on the "NiceAdmin" Bootstrap template by BootstrapMade.
```
