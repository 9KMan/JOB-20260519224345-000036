# Fuel Transaction & Billing Platform

**JOB-20260519224345-000036** | Django · Celery · PostgreSQL · Relay Payments API

---

## Architecture

```
Relay Payments API → Django REST API → PostgreSQL
                              ↓
                      Celery Workers (Redis broker)
                              ↓
              Transaction Polling (15-min) → Invoice Generation (Weekly)
```

---

## Stack

- **Backend:** Django 4.x + Django REST Framework
- **Database:** PostgreSQL
- **Task Queue:** Celery + Celery Beat
- **Message Broker:** Redis
- **PDF:** ReportLab

---

## Project Structure

```
fuel_billing/
├── config/
│   ├── settings.py       # Django settings
│   ├── celery.py         # Celery Beat + task discovery
│   ├── urls.py           # URL routing
│   └── wsgi.py
├── api/
│   ├── models/           # Client, FuelTransaction, Invoice, BillingCycle
│   ├── services/
│   │   ├── relay_api.py             # Relay Payments API client
│   │   ├── transaction_processor.py # Deduplication + normalization
│   │   └── billing.py              # Invoice generation + PDF
│   ├── tasks/            # Celery tasks (pull_transactions, generate_invoices, send_invoices)
│   ├── admin.py          # Django Admin dashboard
│   ├── serializers.py   # DRF serializers
│   └── views.py          # REST API endpoints
├── requirements.txt
└── manage.py
```

---

## Key Features

| Feature | Implementation |
|---------|----------------|
| Relay API Integration | `services/relay_api.py` — paginated sync, 15-min polling, retry on 429 |
| Transaction Dedup | Composite unique constraint on (relay_transaction_id, client_id) |
| Weekly Billing | Celery Beat — Monday 6am UTC, batch invoice generation |
| Invoice PDF | ReportLab — per-client PDF with line items |
| Admin Dashboard | Django Admin — client mgmt, transaction review, invoice actions |

---

## REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/clients/ | List all clients |
| GET | /api/clients/{id}/transactions/ | Client transactions |
| POST | /api/sync/pull/ | Trigger manual Relay API pull |
| POST | /api/invoices/generate/ | Trigger weekly invoice generation |
| GET | /api/invoices/ | List invoices |
| POST | /api/invoices/{id}/send/ | Send invoice to client |
| GET | /api/health/ | Health check |

---

## Celery Tasks

| Task | Schedule | Description |
|------|----------|-------------|
| `pull_transactions_task` | Every 15 min | Sync latest from Relay API |
| `generate_weekly_invoices` | Monday 6am UTC | Create invoices for all clients |
| `send_invoice_emails` | After invoice generation | Deliver invoices |
| `check_invoice_status` | Daily | Update paid/overdue status |

---

## Setup

```bash
pip install -r fuel_billing/requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
celery -A config worker -l info
celery -A config beat -l info
```

---

## Data Model

**Client** — relay_client_id, name, email, billing_config (JSONB), is_active
**FuelTransaction** — relay_transaction_id, client FK, transaction_date, gallons, price_per_gallon, total_amount, is_invoiced, raw_json (JSONB)
**Invoice** — client FK, billing_period_start/end, total_amount, status, pdf_url
**InvoiceLineItem** — invoice FK, fuel_transaction FK, amount
**BillingCycle** — week_start/end, status, invoices_generated