from django.urls import path

from . import views

urlpatterns = [
    path("", views.ReportIndexView.as_view(), name="reports_home"),

    path("profit-loss/", views.ProfitLossView.as_view(), name="profit_loss"),
    path("cash/", views.CashReportView.as_view(), name="report_cash"),
    path("sales/", views.SalesReportView.as_view(), name="sales_report"),
    path("expense-trends/", views.ExpenseTrendView.as_view(), name="expense_trends"),

    path("business/", views.BusinessPerformanceView.as_view(), name="report_business"),
    path("inventory/current/", views.InventoryStockView.as_view(), name="report_inventory_stock"),
    path("customers/debt/", views.CustomerDebtView.as_view(), name="report_customer_debt"),
    path("customers/ageing/", views.DebtAgeingView.as_view(), name="report_debt_ageing"),
    path("suppliers/payables/", views.SupplierPayablesView.as_view(), name="report_supplier_payables"),

    path("business/export/pdf/", views.ExportBusinessOverviewPDFView.as_view(), name="export_business_pdf"),
    path("profit-loss/export/pdf/", views.ExportProfitLossPDFView.as_view(), name="export_profit_loss_pdf"),
    path("profit-loss/export/excel/", views.ExportProfitLossExcelView.as_view(), name="export_profit_loss_excel"),
]