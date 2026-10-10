"""
Run daily via cron (e.g. cPanel's cron job UI: `python manage.py sweep_subscriptions`).

Subscription.refresh_status() already self-heals lazily on every read
(see subscriptions/services.py's get_subscription), so this command
isn't required for correctness - an organization's status is always
accurate whenever anyone actually looks at it. What it's actually for:
sending expiry-reminder emails, which need to go out on a schedule
regardless of whether anyone visits the site that day. No task queue
(Celery etc.) exists in this project yet, so this is the stand-in.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from accounts.emails import logger
from subscriptions.models import Subscription, SubscriptionStatus
from django.core.mail import send_mail
from django.conf import settings


REMINDER_WINDOWS_DAYS = (7, 2, 0)


class Command(BaseCommand):
    help = "Sends renewal-reminder emails and refreshes subscription lifecycle status."

    def handle(self, *args, **options):
        refreshed = 0
        for subscription in Subscription.objects.select_related("organization", "plan").exclude(
            status=SubscriptionStatus.CANCELLED
        ):
            if subscription.refresh_status():
                refreshed += 1
        self.stdout.write(f"Refreshed {refreshed} subscription(s).")

        now = timezone.now()
        reminders_sent = 0
        for subscription in Subscription.objects.select_related("organization", "plan").filter(
            status__in=[SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE]
        ):
            end = subscription.trial_end if subscription.status == SubscriptionStatus.TRIALING else subscription.current_period_end
            if not end:
                continue
            days_left = (end - now).days
            if days_left in REMINDER_WINDOWS_DAYS:
                if self._send_reminder(subscription, days_left):
                    reminders_sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent {reminders_sent} reminder email(s)."))

    def _send_reminder(self, subscription, days_left):
        owner_membership = subscription.organization.memberships.filter(role__slug="owner", is_active=True).first()
        if not owner_membership or not owner_membership.user.email:
            return False

        is_trial = subscription.status == "trialing"
        if days_left == 0:
            subject = f"Your {subscription.plan.name} subscription is due today"
            body_time = "is due today"
        else:
            subject = f"Your {subscription.plan.name} subscription {'trial ' if is_trial else ''}ends in {days_left} days"
            body_time = f"ends in {days_left} days"

        try:
            send_mail(
                subject=subject,
                message=(
                    f"Hi,\n\nYour {subscription.organization.name} subscription "
                    f"({subscription.plan.name}) {body_time}. "
                    f"Visit Settings to renew and keep full access.\n"
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[owner_membership.user.email],
                fail_silently=False,
            )
            return True
        except Exception:
            logger.exception("Failed to send subscription reminder for org %s", subscription.organization_id)
            return False
