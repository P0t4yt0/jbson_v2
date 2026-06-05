from django.urls import path
from . import views

app_name = 'security'

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("forgot-password/", views.forgot_password_view, name="forgot_password"),   
    path("admin/review-resets/", views.admin_review_resets_view, name="review_resets"),
    
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/employee/", views.employee_dashboard, name="employee_dashboard"),

    path("register/", views.register_view, name="register"),
    path("dashboard/admin/users/delete/<int:user_id>/", views.delete_user, name="delete_user"),
    path("edit-user/", views.edit_user_view, name="edit_user_endpoint"),
    path("verify-admin-password/", views.verify_admin_password, name="verify_admin_password"),
    
    path("request-reports-access/", views.request_reports_access, name="request_reports_access"),
    path("review-reports-access/", views.review_reports_access, name="review_reports_access"),
    path("request-settings-access/", views.request_settings_access, name="request_settings_access"),
    path("review-settings-access/", views.review_settings_access, name="review_settings_access"),
]