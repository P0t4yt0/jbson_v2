# user_manual/urls.py
from django.urls import path
from . import views

app_name = 'user_manual'

urlpatterns = [
    path('', views.manual_hub, name='hub'),
    path('dashboard/', views.dashboard_guide, name='dashboard'),
    path('general/', views.general_manual, name='general'),
    path('inventory/', views.inventory_manual, name='inventory'),
    path('pos/', views.pos_manual, name='pos'),
    path('billing/', views.billing_manual, name='billing'),
    path('reports/', views.reports_guide, name='reports'),
    path('management/', views.management_guide, name='management'),
]