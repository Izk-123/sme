# Subscriptions module

Implements the design discussion's subscription/billing architecture:
Organization subscribes (not User), plans carry limits + feature flags,
lifecycle is trial → active → grace → restricted rather than a single
on/off flag.

## Two bugs fixed in code you already had

1. **`Organization.subscription`** was defined as both a `OneToOneField`
   *and* a same-named `@property` - the property silently shadowed the
   field (last class attribute wins in Python), and also collided with
   the reverse accessor `Subscription.organization` already provides via
   `related_name="subscription"`. Fixed: removed both the field and the
   property from `organizations/models.py` - `org.subscription` now
   works purely through the reverse relation.
2. **`accounts/signals.py`'s `create_trial_subscription`** had no
   `@receiver` decorator, so it was never actually called, and it
   assumed `instance` was an `Organization` while attached to `User`'s
   `post_save` - it wouldn't have worked even if connected. Fixed:
   removed from `accounts/signals.py`, correctly reimplemented in
   `subscriptions/signals.py` listening on `Organization`'s `post_save`.

## What's built

- `subscriptions/models.py` - `SubscriptionPlan`, `Subscription` (with
  a `refresh_status()` lifecycle: trialing → grace → restricted, no
  cron required, self-heals on read), `Invoice`, `Payment`.
- `subscriptions/services.py` - `get_subscription()`, `has_feature()`,
  `check_usage_limits()`, `can_downgrade_to()` (blocks a downgrade that
  would put the business over the new plan's limits, per the "don't
  silently remove employees" rule), `upgrade_plan()`,
  `record_manual_payment()`.
- `subscriptions/middleware.py` - `request.subscription`, set from
  `request.organization` (must run after `CurrentMembershipMiddleware`
  - already wired into `config/settings.py`'s `MIDDLEWARE`).
- Views/URLs/templates for `/subscriptions/plans/`,
  `/subscriptions/` (detail + usage dashboard), `/subscriptions/upgrade/`
  - owner-only.
- `python manage.py seed_plans` - Free / Starter / Business / Professional,
  pricing and limits from the design discussion.
- `python manage.py sweep_subscriptions` - optional, cron this daily if
  you want renewal-reminder emails (7 and 2 days out) to actually go
  out on schedule. Not required for correctness - status itself
  refreshes lazily whenever anyone reads it.
- **Barcode scanning is now feature-gated** as the discussion's own
  worked example: `RecordSaleView` passes `barcode_enabled` to the
  template (hides the button, shows an "Upgrade" link instead), and
  the two barcode HTMX endpoints (`BarcodeScanView`,
  `BarcodeScanProductView`) also check server-side - hiding a button
  isn't real enforcement, since someone could just POST the URL
  directly.

## Deliberately NOT built

- **Any payment gateway** (PayChangu, mobile money). `record_manual_payment()`
  is a stand-in for an owner/admin manually confirming a payment
  received outside the system - there's no checkout flow. The Upgrade
  page says this explicitly rather than pretending to charge anyone.
- **WhatsApp/SMS billing reminders** - same reasoning as the earlier
  email-verification work: no provider/credentials exist.
- **Invoice PDF export/download.**
- **Per-branch billing** - `max_branches` exists on the plan but
  nothing in the app currently models branches, so it's not enforced
  anywhere yet.

## Rollout

1. Drop in the files.
2. Fix migration dependencies if needed:
   - `subscriptions/migrations/0001_initial.py` depends on
     `("organizations", "0004_organization_business_size_and_more")` -
     adjust if your organizations app has moved past that.
   - `organizations/migrations/0005_remove_organization_subscription.py`
     is **only needed if you already ran `makemigrations organizations`**
     with the old buggy field present. If you never migrated it into the
     DB, delete this file.
3. `python manage.py migrate`
4. `python manage.py seed_plans`
5. Every *existing* Organization won't have a Subscription row until
   something calls `get_subscription()` for it (which happens
   automatically the first time `SubscriptionMiddleware` touches that
   org, or you can pre-warm all of them in a shell:
   ```python
   from organizations.models import Organization
   from subscriptions.services import get_subscription
   for org in Organization.objects.all():
       get_subscription(org)
   ```
6. (Optional) cron `python manage.py sweep_subscriptions` daily for
   reminder emails.
