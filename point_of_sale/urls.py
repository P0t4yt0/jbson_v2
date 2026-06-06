from django.urls import path
from . import views

app_name = 'point_of_sale'

urlpatterns = [
    # Main View & Cart Operations
    path('', views.pos_view, name='pos_index'),
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('add-by-barcode/', views.add_by_barcode, name='add_by_barcode'),
    path('update-cart-item/', views.update_cart_item, name='update_cart_item'),

    # Checkout & State Management
    path('process-payment/', views.process_payment, name='process_payment'),
    path('void/', views.void_transaction, name='void_transaction'),
    path('reset/', views.reset_transaction, name='reset_transaction'),

    # Quotations System
    path('quotations/', views.quotation_list_view, name='quotation_list'),
    path('save-quotation/<int:transaction_id>/', views.save_as_quotation, name='save_quotation'),
    path('load-quotation/<int:transaction_id>/', views.load_quotation_to_pos, name='load_quotation'),
    path('get-quotation-details/', views.get_quotation_details, name='get_quotation_details'),
    path('print-quotation/<int:transaction_id>/', views.print_quotation, name='print_quotation'),

    # Receipts / Invoicing Utilities
    path('receipt/reprint/<int:txn_id>/', views.reprint_receipt, name='reprint_receipt'),
]