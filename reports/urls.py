# reports/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # --- Hub (NEW) ---
    path("", views.ReportIndexView.as_view(), name="reports_home"),

    # --- Existing ---
    path("profit-loss/", views.ProfitLossView.as_view(), name="profit_loss"),
    path("sales/", views.SalesReportView.as_view(), name="sales_report"),
    path("expense-trends/", views.ExpenseTrendView.as_view(), name="expense_trends"),

    # --- New Reports ---
    path("business/", views.BusinessPerformanceView.as_view(), name="report_business"),
    path("inventory/current/", views.InventoryStockView.as_view(), name="report_inventory_stock"),
    path("customers/debt/", views.CustomerDebtView.as_view(), name="report_customer_debt"),

    # --- Export Endpoints ---
    path("business/export/pdf/", views.ExportBusinessOverviewPDFView.as_view(), name="export_business_pdf"),
    path("profit-loss/export/pdf/", views.ExportProfitLossPDFView.as_view(), name="export_profit_loss_pdf"),
    path("profit-loss/export/excel/", views.ExportProfitLossExcelView.as_view(), name="export_profit_loss_excel"),
]