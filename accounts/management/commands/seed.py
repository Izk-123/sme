# accounts/management/commands/seed.py
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models.signals import post_save

# Import your models
from accounts.models import Role, Membership, UserProfile, UserPreference, NotificationPreference
from organizations.models import Organization
from customers.models import Customer, Payment
from suppliers.models import Supplier
from sales.models import Product, Sale, SaleItem, StockMovement
from expenses.models import ExpenseCategory, Expense
from core.signals import notify_sale_created

User = get_user_model()


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
            # Delete in order of dependency to avoid IntegrityError
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

        self.stdout.write("🌱 Seeding database...")

        # 1. Create the test Organization
        org, _ = Organization.objects.get_or_create(
            name="Acme Retail Shop",
            defaults={
                "business_type": "retail",
                "business_size": "small",
                "currency": "MWK",
            },
        )
        self.stdout.write(f"  ✅ Created Organization: {org.name}")

        # 2. Ensure System Roles exist (depends on your migration 0002)
        # If the migration hasn't run, we create them manually here.
        roles = {}
        for slug, name in [("owner", "Owner"), ("cashier", "Cashier"), ("stock_clerk", "Stock Clerk"), ("accountant", "Accountant")]:
            role, _ = Role.objects.get_or_create(
                slug=slug, organization=None, defaults={"name": name, "is_system": True}
            )
            roles[slug] = role

        # 3. Create Users and Memberships
        users = {}

        # Owner
        owner_user, _ = User.objects.get_or_create(
            username="owner",
            defaults={"email": "owner@example.com", "must_change_password": False},
        )
        owner_user.set_password("password123")
        owner_user.save()
        UserProfile.objects.get_or_create(user=owner_user, defaults={"first_name": "Alice", "last_name": "Owner"})
        UserPreference.objects.get_or_create(user=owner_user)
        NotificationPreference.objects.get_or_create(user=owner_user)
        Membership.objects.get_or_create(user=owner_user, organization=org, defaults={"role": roles["owner"]})
        users["owner"] = owner_user
        self.stdout.write("  ✅ Created Owner user (username: 'owner', password: 'password123')")

        # Cashier
        cashier_user, _ = User.objects.get_or_create(
            username="cashier",
            defaults={"email": "cashier@example.com", "must_change_password": False},
        )
        cashier_user.set_password("password123")
        cashier_user.save()
        UserProfile.objects.get_or_create(user=cashier_user, defaults={"first_name": "Bob", "last_name": "Cashier"})
        UserPreference.objects.get_or_create(user=cashier_user)
        NotificationPreference.objects.get_or_create(user=cashier_user)
        Membership.objects.get_or_create(user=cashier_user, organization=org, defaults={"role": roles["cashier"]})
        users["cashier"] = cashier_user
        self.stdout.write("  ✅ Created Cashier user (username: 'cashier', password: 'password123')")

        # Accountant
        acc_user, _ = User.objects.get_or_create(
            username="accountant",
            defaults={"email": "accountant@example.com", "must_change_password": False},
        )
        acc_user.set_password("password123")
        acc_user.save()
        UserProfile.objects.get_or_create(user=acc_user, defaults={"first_name": "Carol", "last_name": "Accountant"})
        UserPreference.objects.get_or_create(user=acc_user)
        NotificationPreference.objects.get_or_create(user=acc_user)
        Membership.objects.get_or_create(user=acc_user, organization=org, defaults={"role": roles["accountant"]})
        users["accountant"] = acc_user
        self.stdout.write("  ✅ Created Accountant user (username: 'accountant', password: 'password123')")

        # 4. Create Products
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
            prod, _ = Product.objects.get_or_create(
                organization=org,
                name=p["name"],
                defaults={
                    "price": p["price"],
                    "stock_quantity": p["stock"],
                    "low_stock_threshold": 5,
                },
            )
            products.append(prod)
        self.stdout.write(f"  ✅ Created {len(products)} products")

        # 5. Create Customers
        customers_data = [
            {"name": "Chimwemwe Banda", "phone": "088 123 4567", "location": "Lilongwe", "balance": 0},
            {"name": "Mary Mwale", "phone": "099 234 5678", "location": "Blantyre", "balance": 0},
            {"name": "ABC Grocery", "phone": "088 345 6789", "location": "Zomba", "balance": 25000},
            {"name": "Peter Phiri", "phone": "099 456 7890", "location": "Mzuzu", "balance": 0},
            {"name": "Limbe Supermarket", "phone": "088 567 8901", "location": "Blantyre", "balance": 45000},
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
        self.stdout.write(f"  ✅ Created {len(customers)} customers")

        # 6. Create Suppliers
        suppliers_data = [
            {"name": "Wholesale Distributors Ltd", "phone": "099 111 2222", "email": "sales@wholesale.com"},
            {"name": "Bakery Supplies Malawi", "phone": "088 222 3333", "email": "info@bakery.mw"},
            {"name": "Farm Fresh Produce", "phone": "099 333 4444", "email": "farmfresh@gmail.com"},
        ]
        for s in suppliers_data:
            Supplier.objects.get_or_create(
                organization=org,
                name=s["name"],
                defaults={"phone": s["phone"], "email": s["email"]},
            )
        self.stdout.write(f"  ✅ Created {len(suppliers_data)} suppliers")

        # 7. Create Expense Categories
        categories = ["Rent", "Electricity", "Transport", "Salaries", "Packaging", "Internet", "Maintenance"]
        for cat_name in categories:
            ExpenseCategory.objects.get_or_create(organization=org, name=cat_name)
        self.stdout.write(f"  ✅ Created {len(categories)} expense categories")

        # ======== DISCONNECT THE SALE SIGNAL ========
        post_save.disconnect(notify_sale_created, sender=Sale)

        try:
            # 8. Generate Sales and Stock Movements (Last 30 days)
            today = timezone.now().date()
            payment_methods = ["cash", "cash", "airtel_money", "tnm_mpamba", "credit", "credit"]
            sale_count = 0

            for days_ago in range(30, 0, -2):  # 15 sales spread over the last 30 days
                sale_date = timezone.make_aware(timezone.datetime.combine(today - timedelta(days=days_ago), timezone.datetime.min.time()))

                # Pick a random customer (or None for walk-in)
                customer = random.choice([None] + customers)

                # Pick payment method
                payment_method = random.choice(payment_methods)

                sale = Sale.objects.create(
                    organization=org,
                    customer=customer,
                    payment_method=payment_method,
                    created_at=sale_date,
                )

                # Add 1-3 random items to the sale
                items_count = random.randint(1, 3)
                selected_products = random.sample(products, k=min(items_count, len(products)))

                for prod in selected_products:
                    qty = random.randint(1, 3)
                    SaleItem.objects.create(
                        sale=sale,
                        product=prod,
                        quantity=qty,
                        unit_price=prod.price,
                    )
                    # Deduct stock
                    prod.stock_quantity -= qty
                    prod.save()

                    StockMovement.objects.create(
                        organization=org,
                        product=prod,
                        quantity=-qty,
                        movement_type="sale",
                        reference=f"Sale #{sale.pk}",
                        created_at=sale_date,
                    )

                # Recalculate total
                sale.recalculate_total()

                # If credit sale, update customer balance
                if payment_method == "credit" and customer:
                    customer.outstanding_balance += sale.total
                    customer.save()

                sale_count += 1

            # Record some purchase stock movements (to add positive stock)
            for _ in range(5):
                prod = random.choice(products)
                qty = random.randint(10, 20)
                StockMovement.objects.create(
                    organization=org,
                    product=prod,
                    quantity=qty,
                    movement_type="purchase",
                    reference="Initial Stock",
                )
                prod.stock_quantity += qty
                prod.save()

            self.stdout.write(f"  ✅ Created {sale_count} sales transactions with items")

            # 9. Generate Expenses
            expense_categories = ExpenseCategory.objects.filter(organization=org)
            expense_descriptions = ["Monthly rent", "Electricity bill", "Fuel for delivery van", "Staff wages", "Packaging materials", "Internet subscription", "Repairs and maintenance"]

            for days_ago in range(30, 0, -1):
                if random.random() < 0.3:  # 30% chance of an expense per day
                    exp_date = today - timedelta(days=days_ago)
                    category = random.choice(expense_categories)
                    amount = Decimal(random.randint(5000, 150000)) / Decimal(10)  # Random amount
                    expense = Expense.objects.create(
                        organization=org,
                        date=exp_date,
                        category=category,
                        description=random.choice(expense_descriptions),
                        amount=amount,
                        created_by=random.choice(list(users.values())),
                    )

            self.stdout.write("  ✅ Created multiple test expenses")

            # 10. Create some payments against credit customers
            for cust in customers:
                if cust.outstanding_balance > 0:
                    pay_amount = cust.outstanding_balance * Decimal(random.uniform(0.1, 0.3))
                    Payment.objects.create(
                        organization=org,
                        customer=cust,
                        amount=pay_amount,
                        payment_method=random.choice(["cash", "airtel_money", "bank"])[0],
                        created_by=users["cashier"],
                    )
                    cust.outstanding_balance -= pay_amount
                    cust.save()

            self.stdout.write("  ✅ Created partial payments for credit customers")

        finally:
            # ======== RECONNECT THE SALE SIGNAL ========
            post_save.connect(notify_sale_created, sender=Sale)

        self.stdout.write("\n" + "=" * 50)
        self.stdout.write("✅ SEEDING COMPLETE!")
        self.stdout.write("=" * 50)
        self.stdout.write("\nLogin Credentials:")
        self.stdout.write("  Owner:      username='owner'      password='password123'")
        self.stdout.write("  Cashier:    username='cashier'    password='password123'")
        self.stdout.write("  Accountant: username='accountant' password='password123'")
        self.stdout.write(f"\nOrganization: {org.name}")
        self.stdout.write("\nYou can now log in and view the dashboard with real data.")