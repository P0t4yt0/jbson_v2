"""
security/views.py
─────────────────────────────────────────────────────────────────────────────
Security Module – Authentication Views
Product Management System with POS for JBSON Hardware

Handles:
  - User Login  (GET renders form / POST authenticates via Django's bcrypt hasher)
  - User Logout
  - Role-based redirect after login:
      • Administrator  → /dashboard/admin/
      • Employee       → /dashboard/employee/
─────────────────────────────────────────────────────────────────────────────
"""

import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .models import ActivityLog  # Imported for audit logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_client_ip(request):
    """Extract the real client IP, respecting reverse-proxy headers."""
    x_forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded:
        return x_forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _log_activity(user, action: str, description: str, request=None):
    """
    Persist a record to the ActivityLog table.
    Silently ignores failures so auth flow is never blocked.
    """
    try:
        ActivityLog.objects.create(
            user=user,
            action=action,
            description=description,
            ip_address=_get_client_ip(request) if request else None,
            timestamp=timezone.now(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ActivityLog write failed: %s", exc)


def _role_redirect_url(user) -> str:
    """
    Return the appropriate dashboard URL based on the user's role.

    The custom User model exposes a `role` field with two possible values:
        'admin'    → Administrator (full privileges)
        'employee' → Employee (restricted access)
    """
    if getattr(user, "role", "employee") == "admin":
        return "/dashboard/admin/"
    return "/dashboard/employee/"


# ─────────────────────────────────────────────────────────────────────────────
# Login View
# ─────────────────────────────────────────────────────────────────────────────

@never_cache
@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    GET  – render the login form.
    POST – authenticate credentials (Django calls the bcrypt hasher
           configured in settings.PASSWORD_HASHERS) and redirect
           the user to their role-specific dashboard.
    """

    # Already authenticated users are bounced straight to their dashboard.
    if request.user.is_authenticated:
        return redirect(_role_redirect_url(request.user))

    if request.method == "GET":
        return render(request, "security/login.html")

    # ── POST: validate form fields ──────────────────────────────────────────
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")

    if not username or not password:
        messages.error(request, "Please enter both username and password.")
        return render(request, "security/login.html", status=400)

    # ── Authenticate (bcrypt comparison happens inside Django's hasher) ──────
    user = authenticate(request, username=username, password=password)

    if user is None:
        # Log the failed attempt (no user object available, log by username).
        logger.warning(
            "Failed login attempt for username=%r ip=%s",
            username,
            _get_client_ip(request),
        )
        messages.error(request, "Invalid username or password. Please try again.")
        return render(request, "security/login.html", status=401)

    if not user.is_active:
        messages.error(request, "Your account has been deactivated. Contact the administrator.")
        return render(request, "security/login.html", status=403)

    # ── Success ──────────────────────────────────────────────────────────────
    login(request, user)

    # Persist audit trail
    _log_activity(
        user=user,
        action="LOGIN",
        description=f"User '{user.username}' logged in successfully.",
        request=request,
    )

    logger.info("Successful login: username=%r role=%r", user.username, getattr(user, "role", "N/A"))

    redirect_url = _role_redirect_url(user)
    return redirect(redirect_url)


# ─────────────────────────────────────────────────────────────────────────────
# Logout View
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request):
    """
    Logs out the current user, writes an audit entry, then
    redirects to the login page.
    """
    user = request.user

    _log_activity(
        user=user,
        action="LOGOUT",
        description=f"User '{user.username}' logged out.",
        request=request,
    )

    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect("security:login")


# ─────────────────────────────────────────────────────────────────────────────
# Registration View  (Admin-only; opens the account-creation flow)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def register_view(request):
    """
    Only Administrators can create new user accounts.
    - GET  → render the registration form.
    - POST → validate, hash password via bcrypt (Django's hasher),
             save new user, log activity, redirect.
    """
    from .forms import UserRegistrationForm  # Local import to avoid circular deps

    if getattr(request.user, "role", "employee") != "admin":
        messages.error(request, "You do not have permission to access this page.")
        return redirect(_role_redirect_url(request.user))

    if request.method == "GET":
        form = UserRegistrationForm()
        return render(request, "security/register.html", {"form": form})

    form = UserRegistrationForm(request.POST)
    if form.is_valid():
        new_user = form.save(commit=False)
        # set_password() triggers Django's PASSWORD_HASHERS (bcrypt first)
        new_user.set_password(form.cleaned_data["password1"])
        new_user.save()

        _log_activity(
            user=request.user,
            action="USER_CREATED",
            description=(
                f"Admin '{request.user.username}' created account "
                f"'{new_user.username}' with role '{new_user.role}'."
            ),
            request=request,
        )

        messages.success(request, f"Account for '{new_user.username}' created successfully.")
        return redirect("security:register")

    return render(request, "security/register.html", {"form": form}, status=400)

# ─────────────────────────────────────────────────────────────────────────────
# Account Recovery / Forgot Password View
# ─────────────────────────────────────────────────────────────────────────────

@require_http_methods(["GET", "POST"])
def forgot_password_view(request):
    """
    Handles the 4-step account recovery process.
    Step 1: Employee requests reset (Enter username)
    Step 2: Pending admin approval screen
    Step 3: Employee verifies 16-character recovery key
    Step 4: Employee sets new password
    """
    from django.contrib.auth import get_user_model
    # We import EmployeeProfile locally to prevent circular imports, 
    # assuming you add this to your models.py!
    from .models import EmployeeProfile 

    User = get_user_model()
    
    # Default state
    context = {'step': 'request'} 
    
    # Check if the user is already in the middle of the recovery process via sessions
    current_username = request.session.get('reset_username', None)

    if current_username:
        try:
            profile = EmployeeProfile.objects.get(user__username=current_username)
            if profile.reset_approved_by_admin:
                context['step'] = 'verify_key'
            elif profile.reset_requested:
                context['step'] = 'pending_approval'
        except EmployeeProfile.DoesNotExist:
            request.session.pop('reset_username', None)

    if request.method == "POST":
        action = request.POST.get("action")

        # ── FLOW 1: Request Reset ──────────────────────────────────────────
        if action == "request_reset":
            username = request.POST.get("username", "").strip()
            
            try:
                user = User.objects.get(username=username)
                profile, created = EmployeeProfile.objects.get_or_create(user=user)
                
                profile.reset_requested = True
                profile.save()
                
                request.session['reset_username'] = username
                
                # Log the request
                _log_activity(
                    user=user,
                    action="PASSWORD_RESET_REQUEST",
                    description=f"User '{username}' requested a password reset.",
                    request=request,
                )
                messages.success(request, "Your request has been forwarded to the Administrator.")
                
            except User.DoesNotExist:
                # Security Best Practice: Don't reveal if a username exists or not
                messages.success(request, "If that username exists, a request has been forwarded to the Administrator.")
            
            return redirect("security:forgot_password") # Adjust namespace if needed

        # ── FLOW 2: Verify Recovery Key ────────────────────────────────────
        elif action == "verify_key":
            input_key = request.POST.get("recovery_key", "").strip()
            profile = EmployeeProfile.objects.get(user__username=current_username)

            if input_key == profile.recovery_key:
                context['step'] = 'set_new_password'
                messages.success(request, "Key verified! You may now create a new password.")
            else:
                messages.error(request, "Invalid Recovery Key. Please check your spelling and try again.")
                context['step'] = 'verify_key'

        # ── FLOW 3: Set New Password ───────────────────────────────────────
        elif action == "set_password":
            new_password = request.POST.get("new_password")
            confirm_password = request.POST.get("confirm_password")

            if new_password and new_password == confirm_password:
                user = User.objects.get(username=current_username)
                
                # set_password() routes through Django's bcrypt hasher securely
                user.set_password(new_password)
                user.save()

                # Reset the profile flags
                profile = EmployeeProfile.objects.get(user=user)
                profile.reset_requested = False
                profile.reset_approved_by_admin = False
                profile.save()

                # Audit logging
                _log_activity(
                    user=user,
                    action="PASSWORD_CHANGED",
                    description=f"User '{user.username}' successfully reset their password via recovery key.",
                    request=request,
                )

                # Clear session data
                request.session.pop('reset_username', None)
                
                messages.success(request, "Password successfully updated. You may now log in.")
                return redirect("security:login")
            else:
                messages.error(request, "Passwords do not match. Please try again.")
                context['step'] = 'set_new_password'

    return render(request, "security/forgot_password.html", context)