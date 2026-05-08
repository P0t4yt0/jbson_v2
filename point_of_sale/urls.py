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
    path('add-by-barcode/', views.add_by_barcode, name='add_by_barcode'),
]