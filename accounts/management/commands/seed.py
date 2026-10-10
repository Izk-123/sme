"""Seed the database with development data — ChumaFlow / SME Business OS."""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models.signals import post_save
from django.utils import timezone

from accounts.models import (
    Role, Membership, UserProfile, UserPreference, NotificationPreference,
)
from organizations.models import Organization
from customers.models import Customer, Payment
from suppliers.models import Supplier
from sales.models import Product, Sale, SaleItem, StockMovement
from expenses.models import ExpenseCategory, Expense
from core.signals import notify_sale_created

User = get_user_model()


# ---- Category/description pairs so seeded expenses read naturally ----
EXPENSE_PAIRS = [
    ("Rent", "Monthly shop rent"),
    ("Rent", "Storage unit rent"),
    ("Electricity", "ESCOM monthly bill"),
    ("Electricity", "Generator fuel top-up"),
    ("Transport", "Fuel for delivery van"),
    ("Transport", "Minibus fare - stock pickup"),
    ("Salaries", "Staff wages"),
    ("Salaries", "Casual labour payment"),
    ("Packaging", "Packaging materials"),
    ("Packaging", "Bottle labels"),
    ("Internet", "Internet subscription"),
    ("Internet", "Airtime top-up"),
    ("Maintenance", "Repairs and maintenance"),
    ("Maintenance", "Plumbing fix"),
]

# ---- Supplier-linked expense pairs (category, description, supplier name) ----
SUPPLIER_EXPENSE_PAIRS = [
    ("Packaging", "Packaging materials", "Wholesale Distributors Ltd"),
    ("Packaging", "Bottle labels", "Wholesale Distributors Ltd"),
    ("Transport", "Delivery fee - produce pickup", "Farm Fresh Produce"),
]


class Command(BaseCommand):
    help = "Seeds the database with initial test data for development"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help="Delete all existing data (except system roles) before seeding.",
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self.stdout.write("Flushing existing test data...")
            SaleItem.objects.all().delete()
            Sale.objects.all().delete()
            StockMovement.objects.all().delete()
            Product.objects.all().delete()
            Expense.objects.all().delete()
            ExpenseCategory.objects.all().delete()
            Payment.objects.all().delete()
            Customer.objects.all().delete()
            Supplier.objects.all().delete()
            Membership.objects.all().delete()
            User.objects.exclude(is_superuser=True).delete()
            Organization.objects.all().delete()
            self.stdout.write("Data flushed.")

        self.stdout.write("Seeding database...")

        # 1. Organization
        org, _ = Organization.objects.get_or_create(
            name="Acme Retail Shop",
            defaults={
                "business_type": "retail",
                "business_size": "small",
                "currency": "MWK",
            },
        )
        self.stdout.write(f"  [OK] Created Organization: {org.name}")

        # 2. System roles
        roles = {}
        for slug, name in [
            ("owner", "Owner"),
            ("cashier", "Cashier"),
            ("stock_clerk", "Stock Clerk"),
            ("accountant", "Accountant"),
        ]:
            role, _ = Role.objects.get_or_create(
                slug=slug, organization=None,
                defaults={"name": name, "is_system": True},
            )
            roles[slug] = role

        # 3. Users
        users = {}
        for slug, first, last, email in [
            ("owner", "Alice", "Owner", "owner@example.com"),
            ("cashier", "Bob", "Cashier", "cashier@example.com"),
            ("accountant", "Carol", "Accountant", "accountant@example.com"),
        ]:
            u, _ = User.objects.get_or_create(
                username=slug,
                defaults={"email": email, "must_change_password": False},
            )
            u.set_password("password123")
            u.save()
            UserProfile.objects.get_or_create(
                user=u, defaults={"first_name": first, "last_name": last},
            )
            UserPreference.objects.get_or_create(user=u)
            NotificationPreference.objects.get_or_create(user=u)
            Membership.objects.get_or_create(
                user=u, organization=org, defaults={"role": roles[slug]},
            )
            users[slug] = u
            self.stdout.write(f"  [OK] Created {slug} user")

        # 4. Products (with realistic cost_price — ~70% of selling price)
        products_data = [
            {"name": "Maize Flour (2kg)", "price": 1500, "stock": 50},
            {"name": "Cooking Oil (1L)", "price": 3200, "stock": 30},
            {"name": "Sugar (1kg)", "price": 1800, "stock": 40},
            {"name": "Bread (loaf)", "price": 500, "stock": 100},
            {"name": "Salt (500g)", "price": 300, "stock": 80},
            {"name": "Granadilla Wine (750ml)", "price": 1850, "stock": 25},
            {"name": "Chocolate Bar", "price": 1200, "stock": 15},
            {"name": "Detergent (1kg)", "price": 2400, "stock": 20},
        ]
        products = []
        for p in products_data:
            cost = (Decimal(p["price"]) * Decimal("0.70")).quantize(Decimal("10"))
            prod, _ = Product.objects.get_or_create(
                organization=org,
                name=p["name"],
                defaults={
                    "price": p["price"],
                    "cost_price": cost,
                    "stock_quantity": p["stock"],
                    "low_stock_threshold": 5,
                },
            )
            products.append(prod)
        self.stdout.write(f"  [OK] Created {len(products)} products")

        # 5. Customers
        customers_data = [
            {"name": "Chimwemwe Banda", "phone": "088 123 4567",
             "location": "Lilongwe", "balance": 0},
            {"name": "Mary Mwale", "phone": "099 234 5678",
             "location": "Blantyre", "balance": 0},
            {"name": "ABC Grocery", "phone": "088 345 6789",
             "location": "Zomba", "balance": 25000},
            {"name": "Peter Phiri", "phone": "099 456 7890",
             "location": "Mzuzu", "balance": 0},
            {"name": "Limbe Supermarket", "phone": "088 567 8901",
             "location": "Blantyre", "balance": 45000},
        ]
        customers = []
        for c in customers_data:
            cust, _ = Customer.objects.get_or_create(
                organization=org,
                name=c["name"],
                defaults={
                    "phone": c["phone"],
                    "location": c["location"],
                    "outstanding_balance": c["balance"],
                },
            )
            customers.append(cust)
        self.stdout.write(f"  [OK] Created {len(customers)} customers")

        # 6. Suppliers
        suppliers_data = [
            {"name": "Wholesale Distributors Ltd",
             "phone": "099 111 2222", "email": "sales@wholesale.com"},
            {"name": "Bakery Supplies Malawi",
             "phone": "088 222 3333", "email": "info@bakery.mw"},
            {"name": "Farm Fresh Produce",
             "phone": "099 333 4444", "email": "farmfresh@gmail.com"},
        ]
        for s in suppliers_data:
            Supplier.objects.get_or_create(
                organization=org,
                name=s["name"],
                defaults={"phone": s["phone"], "email": s["email"]},
            )
        self.stdout.write(f"  [OK] Created {len(suppliers_data)} suppliers")

        # 7. Expense categories
        categories = [
            "Rent", "Electricity", "Transport", "Salaries",
            "Packaging", "Internet", "Maintenance",
        ]
        for cat_name in categories:
            ExpenseCategory.objects.get_or_create(organization=org, name=cat_name)
        self.stdout.write(f"  [OK] Created {len(categories)} expense categories")

        # Disconnect the sale notification signal during seeding
        post_save.disconnect(notify_sale_created, sender=Sale)

        try:
            today = timezone.localdate()
            local_tz = timezone.get_current_timezone()

            # 8. Sales + stock movements over the last 30 days
            payment_methods = [
                "cash", "cash", "airtel_money", "tnm_mpamba", "credit", "credit",
            ]
            sale_count = 0

            for days_ago in range(30, 0, -2):
                sale_dt = timezone.make_aware(
                    datetime.combine(
                        today - timedelta(days=days_ago), time(12, 0)
                    ),
                    local_tz,
                )
                customer = random.choice([None] + customers)
                payment_method = random.choice(payment_methods)

                sale = Sale.objects.create(
                    organization=org,
                    customer=customer,
                    payment_method=payment_method,
                    created_at=sale_dt,
                )

                items_count = random.randint(1, 3)
                selected_products = random.sample(
                    products, k=min(items_count, len(products)),
                )

                for prod in selected_products:
                    qty = random.randint(1, 3)
                    SaleItem.objects.create(
                        sale=sale, product=prod,
                        quantity=qty, unit_price=prod.price,
                    )
                    prod.stock_quantity -= qty
                    prod.save(update_fields=["stock_quantity"])
                    StockMovement.objects.create(
                        organization=org,
                        product=prod,
                        quantity=-qty,
                        movement_type="sale",
                        reference=f"Sale #{sale.pk}",
                        created_at=sale_dt,
                    )

                sale.recalculate_total()

                if payment_method == "credit" and customer:
                    customer.outstanding_balance += sale.total
                    customer.save(update_fields=["outstanding_balance"])

                sale_count += 1

            # Purchase stock movements — some linked to a real Supplier FK
            org_suppliers = list(Supplier.objects.filter(organization=org))
            for _ in range(5):
                prod = random.choice(products)
                qty = random.randint(10, 20)
                supplier = random.choice(org_suppliers) if org_suppliers else None
                StockMovement.objects.create(
                    organization=org,
                    product=prod,
                    quantity=qty,
                    movement_type="purchase",
                    reference=f"Received via {supplier.name if supplier else 'Manual'}",
                    supplier=supplier,
                )
                prod.stock_quantity += qty
                prod.save(update_fields=["stock_quantity"])

            self.stdout.write(
                f"  [OK] Created {sale_count} sales transactions with items"
            )

            # 9. Expenses — category-matched descriptions, proper supplier FK
            category_map = {
                c.name: c
                for c in ExpenseCategory.objects.filter(organization=org)
            }
            supplier_map = {s.name: s for s in org_suppliers}
            user_list = list(users.values())

            for days_ago in range(30, 0, -1):
                if random.random() >= 0.3:
                    continue
                exp_date = today - timedelta(days=days_ago)

                # 25% of expenses are supplier-linked; the rest aren't
                if random.random() < 0.25 and supplier_map:
                    cat_name, description, supplier_name = random.choice(
                        SUPPLIER_EXPENSE_PAIRS
                    )
                    supplier = supplier_map.get(supplier_name)
                else:
                    cat_name, description = random.choice(EXPENSE_PAIRS)
                    supplier = None

                category = category_map.get(cat_name)
                if category is None:
                    continue

                amount = Decimal(random.randint(5000, 150000)) / Decimal(10)
                Expense.objects.create(
                    organization=org,
                    date=exp_date,
                    category=category,
                    description=description,
                    amount=amount,
                    supplier=supplier,
                    created_by=random.choice(user_list),
                )

            self.stdout.write("  [OK] Created multiple test expenses")

            # 10. Partial payments against credit customers
            for cust in customers:
                if cust.outstanding_balance > 0:
                    pay_amount = (
                        cust.outstanding_balance
                        * Decimal(random.uniform(0.1, 0.3))
                    )
                    Payment.objects.create(
                        organization=org,
                        customer=cust,
                        amount=pay_amount,
                        payment_method=random.choice(
                            ["cash", "airtel_money", "bank"]
                        ),
                        created_by=users["cashier"],
                    )
                    cust.outstanding_balance -= pay_amount
                    cust.save(update_fields=["outstanding_balance"])

            self.stdout.write("  [OK] Created partial payments for credit customers")

        finally:
            post_save.connect(notify_sale_created, sender=Sale)

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("SEEDING COMPLETE!")
        self.stdout.write("=" * 50)
        self.stdout.write("\nLogin Credentials:")
        self.stdout.write("  Owner:      username='owner'      password='password123'")
        self.stdout.write("  Cashier:    username='cashier'    password='password123'")
        self.stdout.write("  Accountant: username='accountant' password='password123'")
        self.stdout.write(f"\nOrganization: {org.name}")
        self.stdout.write(
            "\nYou can now log in and view the dashboard with real data."
        )
