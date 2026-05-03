from django.urls import path
from . import views

app_name = 'inventory' 

urlpatterns = [
    path('products/', views.inventory_list, name='inventory_list'),
    path('products/create/', views.create_product, name='create_product'),
    path('category/add-ajax/', views.add_category_ajax, name='add_category_ajax'),
    path('product/edit/<int:pk>/', views.edit_product, name='edit_product'),
    path('product/delete/<int:pk>/', views.delete_product, name='delete_product'),
    path('supplier/add-ajax/', views.add_supplier_ajax, name='add_supplier_ajax'),
    path('low-stocks/', views.low_stock_view, name='low_stock_view'),
]