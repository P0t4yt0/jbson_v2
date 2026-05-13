from django.urls import path
from . import views

app_name = 'notifications'
urlpatterns = [

    path('api/live/', views.live_notifications_api, name='live_api'),
    path('api/mark-read/', views.mark_all_read_api, name='mark_read_api'), 
    path('read/<int:notif_id>/', views.mark_single_read_and_redirect, name='read_and_redirect'),
]
