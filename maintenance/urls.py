from django.urls import path
from . import views

app_name = 'maintenance' 

urlpatterns = [

    path('', views.maintenance_dashboard, name='maintenance_dashboard'),
]