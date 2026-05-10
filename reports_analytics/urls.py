from django.urls import path
from . import views

app_name = 'reports_analytics'

urlpatterns = [
    path('sales/', views.sales_report_view, name='sales_report'),
    path('procurement/', views.procurement_report, name='procurement_report'),
]