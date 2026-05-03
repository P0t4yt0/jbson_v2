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
from urllib import request

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from django.contrib.auth import get_user_model
import re # We need this to check password rules

# IMPORT NG MODELS: Idinagdag natin ang EmployeeProfile dito sa taas
from .models import ActivityLog, EmployeeProfile  

logger = logging.getLogger(__name__)
User = get_user_model()

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
    if request.user.is_authenticated:
        return redirect(_role_redirect_url(request.user))

    if request.method == "GET":
        return render(request, "security/login.html")

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")

    if not username or not password:
        messages.error(request, "Please enter both username and password.")
        return render(request, "security/login.html", status=400)

    user = authenticate(request, username=username, password=password)

    if user is None:
        logger.warning("Failed login attempt for username=%r ip=%s", username, _get_client_ip(request))
        messages.error(request, "Invalid username or password. Please try again.")
        return render(request, "security/login.html", status=401)

    if not user.is_active:
        messages.error(request, "Your account has been deactivated. Contact the administrator.")
        return render(request, "security/login.html", status=403)

    login(request, user)

    _log_activity(
        user=user,
        action="LOGIN",
        description=f"User '{user.username}' logged in successfully.",
        request=request,
    )

    logger.info("Successful login: username=%r role=%r", user.username, getattr(user, "role", "N/A"))
    return redirect(_role_redirect_url(user))


# ─────────────────────────────────────────────────────────────────────────────
# Logout View
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def logout_view(request):
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
# Registration View  (Admin-only)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def register_view(request):
    from .forms import UserRegistrationForm

    if getattr(request.user, "role", "employee") != "admin":
        messages.error(request, "You do not have permission to access this page.")
        return redirect(_role_redirect_url(request.user))

    if request.method == "GET":
        form = UserRegistrationForm()
        return render(request, "security/register.html", {"form": form})

    form = UserRegistrationForm(request.POST)
    if form.is_valid():
        new_user = form.save(commit=False)
        new_user.set_password(form.cleaned_data["password1"])
        new_user.save()

        _log_activity(
            user=request.user,
            action="USER_CREATED",
            description=f"Admin '{request.user.username}' created account '{new_user.username}' with role '{new_user.role}'.",
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
    """
    context = {'step': 'request'} 
    current_username = request.session.get('reset_username', None)

    if current_username:
        try:
            profile = EmployeeProfile.objects.get(user__username=current_username)
            
            # STATE CHECKING (Na-update para sa seamless redirecting)
            if request.session.get('key_verified'):
                context['step'] = 'set_new_password'
            elif profile.reset_approved_by_admin:
                context['step'] = 'verify_key'
            elif profile.reset_requested:
                context['step'] = 'pending_approval'
        except EmployeeProfile.DoesNotExist:
            request.session.pop('reset_username', None)
            request.session.pop('key_verified', None)

    if request.method == "POST":
        action = request.POST.get("action")

        # ── FLOW 1: Request Reset ──────────────────────────────────────────
        if action == "request_reset":
            username = request.POST.get("username", "").strip()
            try:
                user = User.objects.get(username=username)
                profile, created = EmployeeProfile.objects.get_or_create(user=user)
                
                # THE FIX: I-set sa True ang request, at i-reset sa False ang approval
                profile.reset_requested = True
                profile.reset_approved_by_admin = False 
                profile.save()
                
                request.session['reset_username'] = username
                request.session['key_verified'] = False
                
                _log_activity(
                    user=user,
                    action="PASSWORD_RESET_REQUEST",
                    description=f"User '{username}' requested a password reset.",
                    request=request,
                )
                messages.success(request, "Your request has been forwarded to the Administrator.")
            except User.DoesNotExist:
                messages.success(request, "If that username exists, a request has been forwarded to the Administrator.")
            
            return redirect("security:forgot_password")

        # ── FLOW 2: Verify Recovery Key
        elif action == "verify_key":
            input_key = request.POST.get("recovery_key", "").strip()
            profile = EmployeeProfile.objects.get(user__username=current_username)

            if input_key == profile.recovery_key:
                # Key is correct! Save to session so they stay on Step 4
                request.session['key_verified'] = True
                context['step'] = 'set_new_password'
                messages.success(request, "Key verified! You may now create a new password.")
            else:
                messages.error(request, "Invalid Recovery Key. Please check your spelling and try again.")
                context['step'] = 'verify_key'

        # ── FLOW 3: Set New Password
        elif action == "set_password":
            new_password = request.POST.get("new_password")
            confirm_password = request.POST.get("confirm_password")

            if new_password and new_password == confirm_password:
                user = User.objects.get(username=current_username)
                
                user.set_password(new_password)
                user.save()

                profile = EmployeeProfile.objects.get(user=user)
                profile.reset_requested = False
                profile.reset_approved_by_admin = False
                profile.save()

                _log_activity(
                    user=user,
                    action="PASSWORD_CHANGED",
                    description=f"User '{user.username}' successfully reset their password via recovery key.",
                    request=request,
                )

                request.session.pop('reset_username', None)
                request.session.pop('key_verified', None)
                
                messages.success(request, "Password successfully updated. You may now log in.")
                return redirect("security:login")
            else:
                messages.error(request, "Passwords do not match. Please try again.")
                context['step'] = 'set_new_password'

    # RENDERING LOGIC: I-redirect sa magkahiwalay na HTML based sa step
    if context.get('step') == 'set_new_password':
        return render(request, "security/reset_password.html", context)
    
    return render(request, "security/forgot_password.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Admin Review Requests View
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(["GET", "POST"])
def admin_review_resets_view(request):
    """
    Admin interface to review, approve, or reject employee password reset requests.
    """
    if getattr(request.user, "role", "employee") != "admin":
        messages.error(request, "You do not have permission to access this page.")
        return redirect(_role_redirect_url(request.user))

    if request.method == "POST":
        profile_id = request.POST.get("profile_id")
        action = request.POST.get("action")
        
        try:
            profile = EmployeeProfile.objects.get(id=profile_id)
            
            if action == "approve":
                profile.reset_approved_by_admin = True
                profile.save()
                
                messages.success(
                    request, 
                    f"✅ APPROVED: Securely share this Recovery Key with {profile.user.username}: {profile.recovery_key}"
                )
                
                _log_activity(
                    user=request.user,
                    action="USER_MODIFIED",
                    description=f"Admin '{request.user.username}' approved password reset for '{profile.user.username}'.",
                    request=request,
                )
                
            elif action == "reject":
                profile.reset_requested = False
                profile.reset_approved_by_admin = False
                profile.save()
                
                messages.error(request, f"❌ REJECTED: Reset request for {profile.user.username} was denied.")
                
        except EmployeeProfile.DoesNotExist:
            messages.error(request, "Employee profile not found.")
            
        return redirect("security:review_resets")

    pending_requests = EmployeeProfile.objects.filter(
        reset_requested=True, 
        reset_approved_by_admin=False
    )
    
    return render(request, "security/admin_review_resets.html", {"pending_requests": pending_requests})

User = get_user_model() 

def user_management_view(request):
    if request.method == "POST":
        # 1. Grab the form data
        username = request.POST.get('username')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password') # New field!
        role = request.POST.get('role')
        full_name = request.POST.get('full_name')

        # 2. SAFETY CHECK: Stop the database crash before it happens
        if not full_name:
            messages.error(request, "Error: Full Name was missing from the form. Please hard-refresh your browser (Ctrl+F5) and try again.")
            return redirect('user_management')

        # 3. Check for taken usernames
        if User.objects.filter(username=username).exists():
            messages.error(request, f"The username '{username}' is already taken.")
            return redirect('user_management')
        
        if password != confirm_password:
            messages.error(request, "Passwords do not match. Please try again.")
            return redirect('user_management')
        
        if len(password) < 8 or not re.search(r'\d', password) or not re.search(r'[A-Z]', password):
            messages.error(request, "Password does not meet the security requirements.")
            return redirect('user_management')
            
        # 4. Create the user (Added 'role=role' to keep your database happy!)
        new_user = User.objects.create_user(
            username=username, 
            password=password,
            full_name=full_name,
            role=role 
        )
        
        # 5. Apply Django admin permissions based on the role
        if role == 'Admin':
            new_user.is_staff = True
            new_user.is_superuser = True
        else:
            new_user.is_staff = False
            new_user.is_superuser = False
        
        new_user.save()
        messages.success(request, f"Successfully created {role} account for {full_name}.")
        return redirect('user_management') 

    # 6. Fetch users for the list view
    users = User.objects.all().order_by('-date_created')
    return render(request, 'dashboard/user_management.html', {'users': users})


def settings_hub_view(request):
    return render(request, 'dashboard/settings_hub.html')