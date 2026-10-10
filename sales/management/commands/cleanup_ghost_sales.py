"""Delete zero-total sales and their stock movements."""
from django.core.management.base import BaseCommand
from django.db import transaction

from sales.models import Sale, StockMovement


class Command(BaseCommand):
    help = (
        "Delete zero-total sales (ghosts) and their associated stock movements. "
        "Use --dry-run to preview first."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the sales that would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        ghosts = Sale.objects.filter(total=0).order_by("id")

        count = ghosts.count()
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS("No zero-total sales found. Nothing to do.")
            )
            return

        self.stdout.write(f"Found {count} zero-total sale(s):")
        for s in ghosts:
            self.stdout.write(
                f"  #{s.pk}  org={s.organization_id}  "
                f"customer={s.customer_id or '—'}  "
                f"created={s.created_at:%Y-%m-%d %H:%M}  "
                f"items={s.items.count()}"
            )

        if dry:
            self.stdout.write(
                self.style.WARNING("\n--dry-run: no changes made.")
            )
            return

        # Delete in a transaction so a failure doesn't leave orphans behind.
        with transaction.atomic():
            refs = [f"Sale #{s.pk}" for s in ghosts]
            sm_deleted, _ = StockMovement.objects.filter(
                reference__in=refs
            ).delete()
            sale_deleted, _ = Sale.objects.filter(
                pk__in=[s.pk for s in ghosts]
            ).delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {count} ghost sale(s). "
                f"Cascade rows removed: {sale_deleted} (sales+items), "
                f"{sm_deleted} (stock movements)."
            )
        )
