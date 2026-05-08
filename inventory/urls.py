from django.urls import path
from . import views

app_name = 'inventory' 

urlpatterns = [
    path('products/', views.inventory_list, name='inventory_list'),
    path('run-abc/', views.run_abc_analysis, name='run_abc_analysis'),
    path('product/edit/<int:pk>/', views.edit_product, name='edit_product'),
    path('product/delete/<int:pk>/', views.delete_product, name='delete_product'),
    
    # ETO YUNG BAGONG URL NATIN PARA SA BULK DELETE
    path('bulk-delete/', views.bulk_delete_products, name='bulk_delete_products'),
    
    path('low-stocks/', views.low_stock_view, name='low_stock_view'),
    path('categories/', views.category_list, name='category_list'),
    path('category/edit/<int:pk>/', views.edit_category, name='edit_category'),
    path('category/delete/<int:pk>/', views.delete_category, name='delete_category'),
    path('generate-barcode/', views.barcode_module_view, name='generate_barcode_page'),
]