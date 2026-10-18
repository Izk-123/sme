"""
Repair command: recompute every supplier's outstanding balance from
history.

When to run it
--------------
  * After deploying the opening_balance / on_credit changes.
  * After data imports that bypassed the ORM signals.
  * Whenever a supplier page and a report disagree — that's a sign a
    recompute got skipped (see the docstring in signals.py for why
    that's possible and how it self-heals).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from suppliers.models import Supplier


class Command(BaseCommand):
    help = "Recompute every supplier's outstanding balance from its history."

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            type=int,
            default=None,
            help="Only recompute suppliers for this organization id.",
        )

    def handle(self, *args, **opts):
        qs = Supplier.objects.all()
        if opts["org"] is not None:
            qs = qs.filter(organization_id=opts["org"])

        count = 0
        with transaction.atomic():
            for supplier in qs.iterator():
                supplier.update_balance()
                count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Recomputed {count} suppliers.")
        )