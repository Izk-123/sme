# core/getting_started.py
from django.db.models import Q
from django.urls import reverse

from customers.models import Customer
from expenses.models import Expense
from sales.models import Product, Sale


def build_checklist(org):
    """
    Each step ticks itself from the business's real data. Nothing to store.
    All queries are organization-scoped, so one business can never see
    another business's counts.
    """
    products = Product.objects.filter(organization=org)
    has_products = products.exists()

    # A product with a NULL cost OR a 0 cost can't produce real profit
    # figures. Matches the dashboard banner (core/views.py).
    all_have_cost = has_products and not products.filter(
        Q(cost_price__isnull=True) | Q(cost_price=0)
    ).exists()

    steps = [
        {
            "title": "Add your products",
            "hint": "Name, selling price and how many you have.",
            "url": reverse("product_add"),
            "done": has_products,
            "required": True,
        },
        {
            "title": "Enter what each product cost you",
            "hint": "So ChumaFlow can show your real profit.",
            "url": reverse("inventory_list"),
            "done": all_have_cost,
            "required": True,
        },
        {
            "title": "Record your first sale",
            "hint": "It takes less than a minute.",
            "url": reverse("record_sale"),
            "done": Sale.objects.filter(organization=org).exists(),
            "required": True,
        },
        {
            "title": "Add a customer who owes you money",
            "hint": "So you never forget a debt.",
            "url": reverse("customer_add"),
            "done": Customer.objects.filter(organization=org).exists(),
            "required": False,
        },
        {
            "title": "Record an expense",
            "hint": "Transport, rent, electricity, airtime.",
            "url": reverse("expense_add"),
            "done": Expense.objects.filter(organization=org).exists(),
            "required": False,
        },
        {
            "title": "Invite a staff member (optional)",
            "hint": "Each person gets their own login.",
            "url": reverse("invite_employee"),
            "done": org.memberships.filter(is_active=True).count() > 1,
            "required": False,
        },
    ]

    done = sum(1 for s in steps if s["done"])
    next_step = next((s for s in steps if not s["done"]), None)

    return {
        "steps": steps,
        "next_step": next_step,
        "done": done,
        "total": len(steps),
        "percent": round(done / len(steps) * 100),
        "all_done": done == len(steps),
    }