from django.urls import path
from . import views

# This MUST match the first part of your {% url 'point_of_sale:pos_index' %}
app_name = 'point_of_sale' 

urlpatterns = [
    path('', views.pos_view, name='pos_index'),
    path('void/', views.void_transaction, name='void_transaction'),
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('reset/', views.reset_transaction, name='reset_transaction'),
    path('process-payment/', views.process_payment, name='process_payment'),
    path('quotations/', views.quotation_list_view, name='quotation_list'),
    path('save-quotation/<int:transaction_id>/', views.save_as_quotation, name='save_quotation'),
    path('add-by-barcode/', views.add_by_barcode, name='add_by_barcode'),
    path('update-cart-item/', views.update_cart_item, name='update_cart_item'),
    path('load-quotation/<int:transaction_id>/', views.load_quotation_to_pos, name='load_quotation'),
    path('get-quotation-details/', views.get_quotation_details, name='get_quotation_details'),
    path('receipt/reprint/<int:txn_id>/', views.reprint_receipt, name='reprint_receipt'),
]