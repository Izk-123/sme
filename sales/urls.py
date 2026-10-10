# sales/urls.py
"""
URL routing for the Sales app.
All endpoints are scoped to the current organization via middleware.
"""

from django.urls import path
from . import views

urlpatterns = [
    # ---------- Sales List ----------
    path("", views.SaleListView.as_view(), name="sale_list"),
    
    # ---------- Product CRUD (New!) ----------
    path("product/add/", views.ProductCreateView.as_view(), name="product_add"),
    path("product/<int:pk>/edit/", views.ProductUpdateView.as_view(), name="product_edit"),

    # ---------- Inventory Management ----------
    path("inventory/", views.InventoryListView.as_view(), name="inventory_list"),
    path("receive/", views.ReceiveStockView.as_view(), name="receive_stock"),
    path("valuation/", views.StockValuationView.as_view(), name="stock_valuation"),

    # ---------- Record Sale ----------
    path("record/", views.RecordSaleView.as_view(), name="record_sale"),
    path("record/submit/", views.CreateSaleView.as_view(), name="create_sale"),

    # ---------- HTMX Helpers for Dynamic Sale Form ----------
    path("record/add-row/", views.AddItemRowView.as_view(), name="add_item_row"),
    path("record/remove-row/", views.RemoveItemRowView.as_view(), name="remove_item_row"),
    path("record/calculate/", views.CalculateTotalsView.as_view(), name="calculate_totals"),

    # ---------- Barcode Scanning ----------
    path("scan/", views.BarcodeScanView.as_view(), name="barcode_scan"),
    path("scan-product/", views.BarcodeScanProductView.as_view(), name="barcode_scan_product"),

    # ---------- Product Label Printing ----------
    path("product/<int:pk>/label/", views.ProductLabelView.as_view(), name="product_label"),
]