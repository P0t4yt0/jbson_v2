from django.urls import path
from . import views

app_name = 'reports_analytics'

urlpatterns = [
    path('sales/', views.sales_report_view, name='sales_report'),
    path('purchase/', views.purchase_report_view, name='purchase_report'),
    path('inventory/', views.inventory_report_view, name='inventory_report'),
    path('invoice/', views.invoice_report_view, name='invoice_report'),
    path('procurement/', views.procurement_report, name='procurement_report'),
    path('profit-loss/', views.profit_loss_report_view, name='profit_loss_report'),
    path('annual-report/', views.annual_report_view, name='annual_report'),
    path('hub/', views.reports_hub, name='reports_hub'),
]