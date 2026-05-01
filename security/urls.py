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
app_name = "security"  # namespace for {% url 'security:login' %} etc.

urlpatterns = [
    # ── Authentication ───────────────────────────────────────────────────────
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # ── Account Management (Admin-only) ──────────────────────────────────────
    path("register/", views.register_view, name="register"),
]
