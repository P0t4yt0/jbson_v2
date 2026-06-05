from django.urls import path
from . import views

app_name = 'inventory'

urlpatterns = [
    # Inventory / Products
    path('products/', views.inventory_list, name='inventory_list'),
    path('product/edit/<int:pk>/', views.edit_product, name='edit_product'),
    path('product/delete/<int:pk>/', views.delete_product, name='delete_product'),
    path('bulk-delete/', views.bulk_delete_products, name='bulk_delete_products'),
    path('products/import/preview/', views.preview_csv_import, name='preview_csv_import'),
    path('products/import/confirm/', views.confirm_csv_import, name='confirm_csv_import'),
    path('run-abc/', views.run_abc_analysis, name='run_abc_analysis'),
    path('low-stocks/', views.low_stock_view, name='low_stock_view'),
    path('product/auto-calibrate/', views.auto_calibrate_rop, name='auto_calibrate_rop'),

    # Categories
    path('categories/', views.category_list, name='category_list'),
    path('category/edit/<int:pk>/', views.edit_category, name='edit_category'),
    path('category/delete/<int:pk>/', views.delete_category, name='delete_category'),

    # Suppliers
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/<int:supplier_id>/edit/', views.edit_supplier, name='edit_supplier'),
    path('suppliers/<int:supplier_id>/delete/', views.delete_supplier, name='delete_supplier'),
    path('suppliers/archived/', views.archived_supplier_list, name='archived_supplier_list'),
    path('suppliers/<int:supplier_id>/unarchive/', views.unarchive_supplier, name='unarchive_supplier'),

    # Purchase Orders (PO)
    path('purchase-orders/', views.po_list, name='po_list'),
    path('purchase-orders/create/', views.create_po, name='create_po'),
    path('purchase-orders/<int:po_id>/edit/', views.edit_po, name='edit_po'),
    path('purchase-orders/<int:po_id>/delete/', views.delete_po, name='delete_po'),
    path('purchase-orders/<int:po_id>/receive/', views.receive_po, name='receive_po'),
    path('purchase-orders/<int:po_id>/print/', views.print_po, name='print_po'),

    # Barcodes
    path('generate-barcode/', views.barcode_module_view, name='generate_barcode_page'),
    path('generate-barcode/fetch-batch/<str:batch_id>/', views.fetch_barcode_batch, name='fetch_barcode_batch'),
    path('generate-barcode/delete/<int:pk>/', views.delete_generated_barcode, name='delete_generated_barcode'),
]