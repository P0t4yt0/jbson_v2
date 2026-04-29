from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

urlpatterns = [
    path('',            lambda r: redirect('admin:index')),
    path('admin/',      admin.site.urls),
    path('auth/',       include('security.urls',             namespace='auth')),
    path('inventory/',  include('inventory.urls',            namespace='inventory')),
    path('products/',   include('product_registration.urls', namespace='products')),
    path('pos/',        include('point_of_sale.urls',        namespace='pos')),
    path('billing/',    include('billing_payment.urls',      namespace='billing')),
    path('reports/',    include('reports_analytics.urls',    namespace='reports')),
    path('logs/',       include('activity_log.urls',         namespace='activity_log')),
    path('notifications/', include('notifications.urls',     namespace='notifications')),
    path('maintenance/',include('maintenance.urls',          namespace='maintenance')),
    path('search/',     include('search.urls',               namespace='search')),
    path('manual/',     include('user_manual.urls',          namespace='user_manual')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
