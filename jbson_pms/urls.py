from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.views.generic import TemplateView
from activity_log import views as activity_log_views
from security import views as security_views

urlpatterns = [
    path('',            lambda r: redirect('security:login'), name='home'),
    path('admin/', admin.site.urls),
    path('auth/', include('security.urls')),
    path('dashboard/admin/', TemplateView.as_view(template_name='dashboard/dashboard.html'), name='admin_dashboard'),
    path('inventory/', include('inventory.urls',             namespace='inventory')),
    path('products/',   include('product_registration.urls', namespace='products')),
    path('pos/',        include('point_of_sale.urls',        namespace='pos')),
    path('billing/',    include('billing_payment.urls',      namespace='billing')),
    path('reports/',    include('reports_analytics.urls',    namespace='reports')),
    path('dashboard/admin/activity-logs/', activity_log_views.activity_logs_view, name='activity_logs'),
    path('notifications/', include('notifications.urls',     namespace='notifications')),
    path('maintenance/',include('maintenance.urls',          namespace='maintenance')),
    path('search/',     include('search.urls',               namespace='search')),
    path('manual/',     include('user_manual.urls',          namespace='user_manual')),
    path('dashboard/admin/settings/', security_views.settings_hub_view, name='settings_hub'),
    path('dashboard/admin/users/', security_views.user_management_view, name='user_management'),
    ]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
