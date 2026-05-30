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
    path('generate-barcode/delete/<int:pk>/', views.delete_generated_barcode, name='delete_generated_barcode'), # <-- ADD THIS LINE

    path('suppliers/', views.supplier_list, name='supplier_list'), # <-- ADD THIS LINE
    path('purchase-orders/create/', views.create_po, name='create_po'), # <-- ADD THIS LINE
    path('suppliers/<int:supplier_id>/edit/', views.edit_supplier, name='edit_supplier'),
    path('suppliers/archived/', views.archived_supplier_list, name='archived_supplier_list'),

    path('purchase-orders/', views.po_list, name='po_list'),
    path('purchase-orders/<int:po_id>/receive/', views.receive_po, name='receive_po'),

    path('suppliers/<int:supplier_id>/delete/', views.delete_supplier, name='delete_supplier'),
    path('suppliers/<int:supplier_id>/unarchive/', views.unarchive_supplier, name='unarchive_supplier'),
    path('purchase-orders/<int:po_id>/edit/', views.edit_po, name='edit_po'),
    path('purchase-orders/<int:po_id>/delete/', views.delete_po, name='delete_po'),
    path('product/auto-calibrate/', views.auto_calibrate_rop, name='auto_calibrate_rop'),
    path('purchase-orders/<int:po_id>/print/', views.print_po, name='print_po'),
]   