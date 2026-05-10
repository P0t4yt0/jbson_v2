from django.urls import path
from . import views  # <--- This tells it to look in the CURRENT folder (billing_payment)

app_name = 'billing_payment'
urlpatterns = [
    path('customers/', views.customer_list, name='customer_list'),
    path('customers/<int:pk>/ledger/', views.customer_ledger, name='customer_ledger'),
    path('invoice/<int:invoice_id>/pay/', views.pay_invoice, name='pay_invoice'), 
    path('sales/', views.sales_list, name='sales_list'),
    path('sales/<int:txn_id>/details/', views.transaction_details, name='transaction_details'),
    path('sales/api/<int:txn_id>/', views.get_sale_details_api, name='api_sale_details'),
]
