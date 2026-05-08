"""
security/urls.py
─────────────────────────────────────────────────────────────────────────────
Security Module – URL Configuration
Product Management System with POS for JBSON Hardware

Include this in the project's root urls.py:

    path('auth/', include('security.urls', namespace='security')),

Resulting URL patterns:
    /auth/login/      → login_view
    /auth/logout/     → logout_view
    /auth/register/   → register_view  (Admin-only)
─────────────────────────────────────────────────────────────────────────────
"""

from django.urls import path

from . import views

app_name = 'security'

urlpatterns = [
    # Authentication
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),   
    path('admin/review-resets/', views.admin_review_resets_view, name='review_resets'),

    # Account Management
    path("register/", views.register_view, name="register"),
    path('dashboard/admin/users/delete/<int:user_id>/', views.delete_user, name='delete_user'),
]