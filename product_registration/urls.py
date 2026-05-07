from django.urls import path
from . import views

app_name = 'product_registration' 

urlpatterns = [
    path('add/', views.create_product, name='create_product'),
    path('category/add-ajax/', views.add_category_ajax, name='add_category_ajax'),
    path('supplier/add-ajax/', views.add_supplier_ajax, name='add_supplier_ajax'),
]