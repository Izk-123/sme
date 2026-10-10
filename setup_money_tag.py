"""
==============================================================================
ChumaFlow — `{% money %}` template tag migration installer
==============================================================================

Walks the templates tree, finds every template listed in the migration
guide, and applies the MK{{ ... }} -> {% money ... %} replacements.

Also injects `{% load money %}` where needed, unless the tag library is
already registered as a template builtin.

Files affected:
  customer_list.html       customer_detail.html     expense_list.html
  customer_debt.html       expense_trends.html      inventory_stock.html
  profit_loss.html         sales_report.html        business_performance.html
  _receipt.html            inventory_list.html      product_label.html
  sale_list.html           stock_valuation.html     supplier_list.html
  supplier_detail.html     _item_row.html           _grand_total.html

Run from the project root:
    python setup_money_tag.py

Idempotent. Preserves line endings. UTF-8.
==============================================================================
"""
from pathlib import Path
import re
import sys


BASE = Path.cwd()


# ------------------------------------------------------------------------------
# Guard: must be in a Django project root
# ------------------------------------------------------------------------------

if not (BASE / "manage.py").exists():
    print(f"ERROR: manage.py not found in {BASE}")
    print("Run this script from the Django project root.")
    sys.exit(1)


# ------------------------------------------------------------------------------
# Is the `money` templatetag available?
#
# The migration guide says "assuming you've added core.templatetags.money
# to TEMPLATES['OPTIONS']['builtins']". If you have, `{% load money %}`
# isn't strictly required — but it's still harmless. If you haven't, we
# need to inject the load line into each template.
# ------------------------------------------------------------------------------

def money_tag_exists():
    """Return True if a `money` templatetag module exists anywhere."""
    for p in BASE.rglob("money.py"):
        if "templatetags" in p.parts:
            return True
    return False


MONEY_TAG_AVAILABLE = money_tag_exists()


# ------------------------------------------------------------------------------
# I/O helpers — preserve line endings exactly
# ------------------------------------------------------------------------------

def read(path):
    """Read text as UTF-8 without newline translation."""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write(path, text):
    """Write text as UTF-8 without newline translation."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def find_all(name):
    """
    Find every template file named `name` under templates/ or core/templates/.

    Returns a list of Path objects. Empty if not found.
    """
    roots = [BASE / "templates", BASE / "core" / "templates"]
    found = []
    for root in roots:
        if root.exists():
            found.extend(root.rglob(name))
    return found


# ------------------------------------------------------------------------------
# `{% load money %}` injection
# ------------------------------------------------------------------------------

def has_money_load(text):
    """True if a `{% load ... money ... %}` tag is already present."""
    return bool(re.search(r"{%\s*load\b[^%]*\bmoney\b[^%]*%}", text))


def ensure_money_load(text):
    """
    Ensure `{% load money %}` appears near the top of the file.

    Insertion rules (in order):
      1. Right after the first `{% extends ... %}` line
      2. Right after the first `{% load ... %}` line
      3. At the very top of the file

    Returns (new_text, was_added).
    """
    if has_money_load(text):
        return text, False

    # Detect the file's newline style
    m = re.search(r"\r\n|\n|\r", text)
    nl = m.group(0) if m else "\n"

    # splitlines with keepends preserves every existing line ending
    lines = text.splitlines(keepends=True)

    for i, line in enumerate(lines[:20]):
        stripped = line.rstrip("\r\n")
        # Match "{% extends ... %}" or "{% load ... %}"
        if re.match(r"^\s*{%\s*(extends|load)\b", stripped):
            lines.insert(i + 1, "{% load money %}" + nl)
            return "".join(lines), True

    # Nothing matched — insert at the very top
    lines.insert(0, "{% load money %}" + nl)
    return "".join(lines), True


# ------------------------------------------------------------------------------
# Replacement table — taken verbatim from the migration guide
#
# Format: filename -> list of (old_fragment, new_fragment)
# Order matters when one pattern is a substring of another; longest first.
# ------------------------------------------------------------------------------

REPLACEMENTS = {
    "customer_list.html": [
        ("MK{{ customer.outstanding_balance|floatformat:2 }}",
         "{% money customer.outstanding_balance %}"),
    ],

    "customer_detail.html": [
        ("MK{{ customer.outstanding_balance|floatformat:2 }}",
         "{% money customer.outstanding_balance %}"),
        ("MK{{ sale.total|floatformat:2 }}",
         "{% money sale.total %}"),
        ("MK{{ payment.amount|floatformat:2 }}",
         "{% money payment.amount %}"),
    ],

    "expense_list.html": [
        ("MK{{ expense.amount|floatformat:2 }}",
         "{% money expense.amount %}"),
    ],

    "customer_debt.html": [
        ("MK{{ total_debt|floatformat:2 }}",
         "{% money total_debt %}"),
        ("MK{{ customer.outstanding_balance|floatformat:2 }}",
         "{% money customer.outstanding_balance %}"),
    ],

    "expense_trends.html": [
        ("MK{{ yearly_total|floatformat:2 }}",
         "{% money yearly_total %}"),
        ("MK{{ average|floatformat:2 }}",
         "{% money average %}"),
        ("MK{{ max_value|floatformat:2 }}",
         "{% money max_value %}"),
        ("MK{{ min_value|floatformat:2 }}",
         "{% money min_value %}"),
        # Applies to every `{{ amount|floatformat:2 }}` in the file
        # (the migration guide lists 3 occurrences in the monthly table).
        ("{{ amount|floatformat:2 }}",
         "{% money amount %}"),
    ],

    "inventory_stock.html": [
        ("MK{{ total_value|floatformat:2 }}",
         "{% money total_value %}"),
        ("MK{{ product.price|floatformat:2 }}",
         "{% money product.price %}"),
        ("MK{{ product.total_value|floatformat:2 }}",
         "{% money product.total_value %}"),
    ],

    "profit_loss.html": [
        ("MK{{ revenue|floatformat:2 }}",
         "{% money revenue %}"),
        ("MK{{ expenses|floatformat:2 }}",
         "{% money expenses %}"),
        ("MK{{ net_profit|floatformat:2 }}",
         "{% money net_profit %}"),
    ],

    "sales_report.html": [
        ("MK{{ total_sales_revenue|floatformat:2 }}",
         "{% money total_sales_revenue %}"),
        ("MK{{ product.total_revenue|floatformat:2 }}",
         "{% money product.total_revenue %}"),
        ("MK{{ customer.total_spent|floatformat:2 }}",
         "{% money customer.total_spent %}"),
    ],

    "business_performance.html": [
        ("MK{{ current.total_sales|floatformat:2 }}",
         "{% money current.total_sales %}"),
        ("MK{{ current.total_expenses|floatformat:2 }}",
         "{% money current.total_expenses %}"),
        ("MK{{ current.gross_profit|floatformat:2 }}",
         "{% money current.gross_profit %}"),
        ("MK{{ current.customer_credit|floatformat:2 }}",
         "{% money current.customer_credit %}"),
    ],

    "_receipt.html": [
        # Longest first so `sale.total` doesn't shadow `item.subtotal`
        ("MK{{ item.subtotal }}", "{% money item.subtotal %}"),
        ("MK{{ sale.total }}",    "{% money sale.total %}"),
    ],

    "inventory_list.html": [
        ("MK{{ product.price|floatformat:2 }}",
         "{% money product.price %}"),
        ("MK{{ product.stock_value|floatformat:2 }}",
         "{% money product.stock_value %}"),
    ],

    "product_label.html": [
        ("MK{{ product.price }}", "{% money product.price %}"),
    ],

    "sale_list.html": [
        ("MK{{ today_sales|floatformat:0 }}",
         "{% money today_sales %}"),
        ("MK{{ sale.total|floatformat:2 }}",
         "{% money sale.total %}"),
    ],

    "stock_valuation.html": [
        ("MK{{ total_value|floatformat:2 }}",
         "{% money total_value %}"),
        ("MK{{ product.price|floatformat:2 }}",
         "{% money product.price %}"),
        ("MK{{ product.total_value|floatformat:2 }}",
         "{% money product.total_value %}"),
    ],

    "supplier_list.html": [
        ("MK{{ supplier.outstanding_balance|floatformat:2 }}",
         "{% money supplier.outstanding_balance %}"),
    ],

    "supplier_detail.html": [
        ("MK{{ supplier.outstanding_balance|floatformat:2 }}",
         "{% money supplier.outstanding_balance %}"),
    ],

    "_item_row.html": [
        ("{{ p.name }} · MK{{ p.price }}",
         "{{ p.name }} · {% money p.price %}"),
    ],

    # `_grand_total.html` is created below if it doesn't exist.
    "_grand_total.html": [
        ('MK{{ total|default:"0" }}', "{% money total %}"),
    ],
}


# ------------------------------------------------------------------------------
# Per-file processing
# ------------------------------------------------------------------------------

def process_file(path, pairs):
    """
    Apply all (old, new) pairs to `path` and ensure the money-load tag.

    Returns a dict:
      {'replacements': int, 'load_added': bool, 'changed': bool}
    """
    text = read(path)
    original = text

    total = 0
    for old, new in pairs:
        n = text.count(old)
        if n:
            text = text.replace(old, new)
            total += n

    load_added = False
    if total and not MONEY_TAG_AVAILABLE:
        # Only inject the load line if the tag isn't a builtin — otherwise
        # the file would still work but with a redundant line.
        pass

    # Even if builtins is configured, an explicit `{% load money %}` is
    # harmless and makes the template self-documenting. Inject it whenever
    # at least one replacement happened and the tag exists on disk.
    if total and MONEY_TAG_AVAILABLE:
        text, load_added = ensure_money_load(text)

    changed = text != original
    if changed:
        write(path, text)

    return {
        "replacements": total,
        "load_added": load_added,
        "changed": changed,
    }


# ------------------------------------------------------------------------------
# Banner
# ------------------------------------------------------------------------------

print()
print("=" * 70)
print(" ChumaFlow — {% money %} migration")
print("=" * 70)
print()

if MONEY_TAG_AVAILABLE:
    print("  money templatetag: found")
else:
    print("  money templatetag: NOT FOUND")
    print("    -> You must create core/templatetags/money.py and register it")
    print("       in TEMPLATES['OPTIONS']['builtins'] before this migration")
    print("       will render correctly. The script will still apply the")
    print("       replacements, but templates will error until the tag exists.")
    print()

print()


# ------------------------------------------------------------------------------
# Walk the replacement table
# ------------------------------------------------------------------------------

total_files_patched = 0
total_files_already = 0
total_files_missing = 0
total_replacements = 0
total_load_added = 0

# Sorted for stable output
for filename in sorted(REPLACEMENTS.keys()):
    pairs = REPLACEMENTS[filename]
    matches = find_all(filename)

    if not matches:
        print(f"  - {filename:32s}  not found in templates/")
        total_files_missing += 1
        continue

    for path in matches:
        rel = path.relative_to(BASE)
        result = process_file(path, pairs)

        if result["changed"]:
            parts = [f"{result['replacements']} replacement"
                     f"{'s' if result['replacements'] != 1 else ''}"]
            if result["load_added"]:
                parts.append("load injected")
            print(f"  + {str(rel):60s}  ({', '.join(parts)})")
            total_files_patched += 1
            total_replacements += result["replacements"]
            if result["load_added"]:
                total_load_added += 1
        else:
            print(f"  = {str(rel):60s}  already migrated")
            total_files_already += 1


# ------------------------------------------------------------------------------
# Special case: create _grand_total.html if it doesn't exist
# ------------------------------------------------------------------------------

print()
print("  _grand_total.html:")

grand_total_matches = find_all("_grand_total.html")
if grand_total_matches:
    # Already handled in the loop above (it was in REPLACEMENTS)
    print(f"    = already handled above ({len(grand_total_matches)} copy/ies)")
else:
    target = BASE / "templates" / "sales" / "_grand_total.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "{% load money %}\n"
        '<span class="h4 mb-0 money text-primary">{% money total %}</span>\n',
        encoding="utf-8",
    )
    print(f"    + created {target.relative_to(BASE)}")
    total_files_patched += 1


# ------------------------------------------------------------------------------
# Report
# ------------------------------------------------------------------------------

print()
print("=" * 70)
print(" Summary")
print("=" * 70)
print()
print(f"  Files patched:        {total_files_patched}")
print(f"  Files already done:   {total_files_already}")
print(f"  Files not found:      {total_files_missing}")
print(f"  Total replacements:   {total_replacements}")
print(f"  Load lines injected:  {total_load_added}")
print()


# ------------------------------------------------------------------------------
# Verification
# ------------------------------------------------------------------------------

print("=" * 70)
print(" Verification")
print("=" * 70)
print()
print("  Search for any remaining hardcoded MK{{ patterns:")
print()
print("    PowerShell:")
print('      Get-ChildItem -Recurse -Filter *.html templates |'
      ' Select-String "MK\\{\\{"')
print()
print("    Bash / Git Bash:")
print('      grep -rn "MK{{" templates/ core/templates/ 2>/dev/null')
print()
print("  Expected: zero matches, except for intentional mockup text like")
print("  `MK 185,000` on the landing page (which uses a space, not `MK{{`).")
print()


# ------------------------------------------------------------------------------
# Notes
# ------------------------------------------------------------------------------

print("=" * 70)
print(" Notes")
print("=" * 70)
print()
print("  * expense_trends.html — the monthly breakdown table header still")
print("    reads `Amount (MK)`, so every cell will now display an extra")
print("    `MK` prefix. Either change the header to just `Amount`, or")
print("    accept the redundancy. The migration guide calls this out.")
print()
print("  * Templates NOT modified (form-only or no money output):")
print("      payment_form.html, expense_form.html, product_form.html,")
print("      receive_stock.html, record_sale.html (except via its")
print("      include of _grand_total.html, handled above).")
print()
if not MONEY_TAG_AVAILABLE:
    print("  * CRITICAL: core/templatetags/money.py was NOT found. Create it")
    print("    and add `core.templatetags.money` to TEMPLATES['OPTIONS']")
    print("    ['builtins'] in config/settings.py, or the templates will")
    print("    raise TemplateSyntaxError on render.")
    print()