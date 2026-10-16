# sales/utils.py (create this file)
import random
import string

def generate_barcode():
    """Generate a simple 12-digit numeric barcode (EAN-13 compatible)."""
    return ''.join(random.choices(string.digits, k=12))