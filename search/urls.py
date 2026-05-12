from django.urls import path
from . import views

app_name = 'search'

urlpatterns = [
    path('api/global-search/', views.global_search_api, name='global_search_api'),
]