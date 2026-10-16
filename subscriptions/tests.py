from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Role, User, UserProfile
from organizations.models import Organization
from sales.models import Product, Sale
from subscriptions.models import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


class RestrictedSubscriptionBlocksWritesTests(TestCase):
    """
    Proves RESTRICTED actually means something. If any write view
    forgets SubscriptionWriteRequiredMixin, one of the _is_blocked
    assertions fails - that's the point.

    URL names below are the ones actually registered in sales/urls.py:
        record_sale  -> /sales/record/        (GET-only TemplateView, renders the form)
        create_sale  -> /sales/record/submit/ (POST target - the real write path)
        product_add  -> /sales/product/add/   (ProductCreateView)
        product_edit -> /sales/product/<pk>/edit/ (ProductUpdateView)
        sale_list    -> /sales/
        inventory_list -> /sales/inventory/

    The record_sale/create_sale split is the standard HTMX pattern: one
    view renders the form, a different view handles the submission.
    POSTing at record_sale returns 405 (TemplateView has no post()) and
    never reaches the write path - hence the test targets create_sale.
    """

    def setUp(self):
        # ----------------------------------------------------------------
        # Order matters here. Creating an Organization fires
        # subscriptions.signals.create_trial_subscription ->
        # services.start_trial(), which looks up a plan with slug
        # "business" then falls back to "free". If neither exists yet,
        # start_trial() passes plan=None into Subscription.objects.create
        # and we die on a NOT NULL constraint. So: plans first, org second.
        # ----------------------------------------------------------------
        SubscriptionPlan.objects.create(
            name="Free", slug="free", sort_order=0,
            price_monthly=0, price_annual=0,
            max_users=1, max_products=10, max_branches=1,
            max_transactions_month=50, features={},
        )
        self.plan = SubscriptionPlan.objects.create(
            name="Business", slug="business", sort_order=2,
            price_monthly=25000, price_annual=250000,
            max_users=10, max_products=0, max_branches=3,
            max_transactions_month=0, features={"barcode": True},
        )

        # The signal will attach a TRIALING subscription on this plan.
        self.org = Organization.objects.create(name="Test Co")

        # Reuse the subscription the signal just created - don't create a
        # second one, the OneToOneField would reject it. Flip it to
        # RESTRICTED, which is the state these tests are about.
        self.subscription = self.org.subscription
        self.subscription.status = SubscriptionStatus.RESTRICTED
        self.subscription.grace_end = timezone.now() - timedelta(days=1)
        self.subscription.save(update_fields=["status", "grace_end"])

        # ----------------------------------------------------------------
        # Owner + membership. must_change_password is set explicitly to
        # False so ForcePasswordChangeMiddleware doesn't redirect every
        # request to /change-password and mask the real assertions.
        # ----------------------------------------------------------------
        self.owner = User.objects.create_user(
            username="owner", password="x", email="o@example.com",
        )
        self.owner.must_change_password = False
        self.owner.save(update_fields=["must_change_password"])

        UserProfile.objects.create(user=self.owner, first_name="Owner")
        Membership.objects.create(
            user=self.owner,
            organization=self.org,
            role=Role.get_system("owner"),
            is_active=True,
        )

        # A product to rename in the update-blocked test.
        self.product = Product.objects.create(
            organization=self.org,
            name="Widget",
            price=100,
            stock_quantity=50,
        )

        self.client.force_login(self.owner)

    # --------------------------------------------------------------------
    # Write paths - each must be redirected to subscription_detail.
    # --------------------------------------------------------------------

    def test_create_sale_is_blocked(self):
        # POST to create_sale (CreateSaleView), not record_sale.
        # record_sale is a GET-only TemplateView that just renders the
        # form; POSTing to it returns 405 and never reaches the write
        # path where SubscriptionWriteRequiredMixin lives.
        resp = self.client.post(reverse("create_sale"), {})
        self.assertRedirects(resp, reverse("subscription_detail"))
        self.assertEqual(Sale.objects.count(), 0)

    def test_product_create_is_blocked(self):
        # product_add, not product_create - see sales/urls.py.
        resp = self.client.post(reverse("product_add"), {
            "name": "New", "price": "50", "stock_quantity": "1",
        })
        self.assertRedirects(resp, reverse("subscription_detail"))
        self.assertFalse(Product.objects.filter(name="New").exists())

    def test_product_update_is_blocked(self):
        resp = self.client.post(
            reverse("product_edit", args=[self.product.pk]),
            {"name": "Renamed", "price": "100", "stock_quantity": "50"},
        )
        self.assertRedirects(resp, reverse("subscription_detail"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, "Widget")

    # --------------------------------------------------------------------
    # Read paths - must still render. This is the whole point of
    # RESTRICTED: no writes, but data stays visible/exportable.
    # --------------------------------------------------------------------

    def test_sale_list_still_renders(self):
        resp = self.client.get(reverse("sale_list"))
        self.assertEqual(resp.status_code, 200)

    def test_inventory_list_still_renders(self):
        resp = self.client.get(reverse("inventory_list"))
        self.assertEqual(resp.status_code, 200)