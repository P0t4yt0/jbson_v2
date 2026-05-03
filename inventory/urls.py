from django.urls import path
from . import views

app_name = 'inventory' 

urlpatterns = [
    path('products/', views.inventory_list, name='inventory_list'),
    path('products/create/', views.create_product, name='create_product'),
    path('low-stocks/', views.low_stock_view, name='low_stock_view'),
]