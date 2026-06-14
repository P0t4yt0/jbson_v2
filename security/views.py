import json
import logging
import re
from functools import wraps
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Sum, DecimalField, F
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from activity_log.utils import log_system_activity
from billing_payment.models import SalesReturn
from inventory.models import InventoryItem
from notifications.models import Notification
from point_of_sale.models import Transaction
from .models import ActivityLog, EmployeeProfile
from inventory.models import ProductBatch

logger = logging.getLogger(__name__)
User = get_user_model()

def settings_access_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        role = getattr(request.user, 'role', 'employee').lower()
        
        if role == 'employee' and not request.user.is_superuser:
            profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
            
            if not profile.has_valid_settings_access:
                was_expired = False
                if profile.settings_access_approved:
                    profile.settings_access_approved = False
                    profile.settings_access_expires_at = None
                    profile.save()
                    was_expired = True
                
                return render(request, 'dashboard/settings_access_request.html', {
                    'profile': profile,
                    'was_expired': was_expired
                })
                
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def _get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', 'unknown')

def _log_activity(user, action: str, description: str, request=None):
    try:
        ActivityLog.objects.create(
            user=user,
            action=action,
            description=description,
            ip_address=_get_client_ip(request) if request else None,
            timestamp=timezone.now(),
        )
    except Exception as exc:
        logger.warning('ActivityLog write failed: %s', exc)

def _role_redirect_url(user) -> str:
    if getattr(user, 'role', 'employee') == 'admin':
        return '/dashboard/admin/'
    return '/pos/'

@never_cache
@require_http_methods(['GET', 'POST'])
def login_view(request):
    if request.user.is_authenticated:
        return redirect(_role_redirect_url(request.user))

    if request.method == 'GET':
        return render(request, 'security/login.html')

    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')

    if not username or not password:
        messages.error(request, 'Please enter both username and password.')
        return render(request, 'security/login.html', status=400)

    user = authenticate(request, username=username, password=password)
    
    if user is None:
        logger.warning('Failed login attempt for username=%r ip=%s', username, _get_client_ip(request))
        messages.error(request, 'Invalid username or password. Please try again.')
        return render(request, 'security/login.html', status=401)

    if not user.is_active:
        messages.error(request, 'Your account has been deactivated. Contact the administrator.')
        return render(request, 'security/login.html', status=403)

    login(request, user)

    _log_activity(
        user=user,
        action='LOGIN',
        description=f"User '{user.username}' logged in successfully.",
        request=request,
    )
    logger.info('Successful login: username=%r role=%r', user.username, getattr(user, 'role', 'N/A'))

    if user.role == 'admin':
        return redirect('admin_dashboard') 
    elif user.role == 'employee':
        return redirect('employee_dashboard') 
        
    return redirect(_role_redirect_url(user))

@login_required
@require_http_methods(['GET', 'POST'])
def logout_view(request):
    user = request.user

    _log_activity(
        user=user,
        action='LOGOUT',
        description=f"User '{user.username}' logged out.",
        request=request,
    )

    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('security:login')

@login_required
@require_http_methods(['GET', 'POST'])
def register_view(request):
    from .forms import UserRegistrationForm

    if getattr(request.user, 'role', 'employee') != 'admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect(_role_redirect_url(request.user))

    if request.method == 'GET':
        form = UserRegistrationForm()
        return render(request, 'security/register.html', {'form': form})

    form = UserRegistrationForm(request.POST)
    if form.is_valid():
        new_user = form.save(commit=False)
        new_user.set_password(form.cleaned_data['password1'])
        new_user.save()
        messages.success(request, f"Account for '{new_user.username}' created successfully.")
        return redirect('security:register')

    return render(request, 'security/register.html', {'form': form}, status=400)

@require_http_methods(['GET', 'POST'])
def forgot_password_view(request):
    context = {'step': 'request'} 
    current_username = request.session.get('reset_username', None)

    if current_username:
        try:
            profile = EmployeeProfile.objects.get(user__username=current_username)
            check_mode = request.GET.get('check') == 'status'

            if request.session.get('key_verified'):
                context['step'] = 'set_new_password'
            elif profile.reset_approved_by_admin:
                context['step'] = 'verify_key'
                if check_mode:
                    messages.success(request, 'Success! Request approved. Please enter the Recovery Key from your Admin.')
            elif profile.reset_requested:
                context['step'] = 'pending_approval'
                if check_mode:
                    messages.error(request, 'Your request is still pending. Please contact your Admin for approval.')
        except EmployeeProfile.DoesNotExist:
            request.session.pop('reset_username', None)

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'request_reset':
            username = request.POST.get('username', '').strip()
            try:
                user = User.objects.get(username=username)
                profile, created = EmployeeProfile.objects.get_or_create(user=user)
                
                profile.reset_requested = True
                profile.reset_approved_by_admin = False 
                profile.save()
                
                request.session['reset_username'] = username
                request.session['key_verified'] = False
                
                _log_activity(
                    user=user,
                    action='PASSWORD_RESET_REQUEST',
                    description=f"User '{username}' requested a password reset.",
                    request=request,
                )

                admins = User.objects.filter(role='Admin', is_active=True)
                for admin_user in admins:
                    Notification.objects.create(
                        user=admin_user,
                        notification_type='password_reset', 
                        priority='high',
                        title='Password Reset Request',
                        message=f"Employee '{username}' requested a password reset. Review pending requests.",
                        action_url=reverse('user_management')
                    )

                messages.success(request, 'Your request has been forwarded to the Administrator.')
            except User.DoesNotExist:
                messages.success(request, 'If that username exists, a request has been forwarded to the Administrator.')
            
            return redirect('security:forgot_password')

        elif action == 'verify_key':
            input_key = request.POST.get('recovery_key', '').strip()
            profile = EmployeeProfile.objects.get(user__username=current_username)

            if input_key == profile.recovery_key:
                request.session['key_verified'] = True
                context['step'] = 'set_new_password'
                messages.success(request, 'Key verified! You may now create a new password.')
            else:
                messages.error(request, 'Invalid Recovery Key. Please check your spelling and try again.')
                context['step'] = 'verify_key'

        elif action == 'set_password':
            new_password = request.POST.get('new_password')
            confirm_password = request.POST.get('confirm_password')

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
                    action='PASSWORD_CHANGED',
                    description=f"User '{user.username}' successfully reset their password via recovery key.",
                    request=request,
                )

                request.session.pop('reset_username', None)
                request.session.pop('key_verified', None)
                
                messages.success(request, 'Password successfully updated. You may now log in.')
                return redirect('security:login')
            else:
                messages.error(request, 'Passwords do not match. Please try again.')
                context['step'] = 'set_new_password'

    return render(request, 'security/forgot_password.html', context)

@login_required
@require_http_methods(['GET', 'POST'])
def admin_review_resets_view(request):
    if getattr(request.user, 'role', 'employee') != 'admin':
        messages.error(request, 'You do not have permission to access this page.')
        return redirect(_role_redirect_url(request.user))

    if request.method == 'POST':
        profile_id = request.POST.get('profile_id')
        action = request.POST.get('action')
        
        try:
            profile = EmployeeProfile.objects.get(id=profile_id)
            
            if action == 'approve':
                profile.reset_approved_by_admin = True
                profile.save()
                
                messages.success(
                    request, 
                    f"Securely share this Recovery Key with {profile.user.username}: {profile.recovery_key}"
                )
                
                _log_activity(
                    user=request.user,
                    action='USER_MODIFIED',
                    description=f"Admin '{request.user.username}' approved password reset for '{profile.user.username}'.",
                    request=request,
                )
                
            elif action == 'reject':
                profile.reset_requested = False
                profile.reset_approved_by_admin = False
                profile.save()
                messages.error(request, f"Reset request for {profile.user.username} was denied.")
                
        except EmployeeProfile.DoesNotExist:
            messages.error(request, 'Employee profile not found.')
            
        return redirect('user_management')

    pending_requests = EmployeeProfile.objects.filter(
        reset_requested=True, 
        reset_approved_by_admin=False
    )
    return render(request, 'security/admin_review_resets.html', {'pending_requests': pending_requests})

@login_required
def admin_dashboard(request):
    if getattr(request.user, 'role', 'employee') != 'admin':
        messages.error(request, 'Access denied. Admin privileges required.')
        return redirect('security:employee_dashboard')

    total_sales = Transaction.objects.filter(status__in=['completed', 'paid']).aggregate(
        total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField())
    )['total']

    sales_return = SalesReturn.objects.aggregate(
        total=Coalesce(Sum('total_refund'), 0, output_field=DecimalField())
    )['total']

    profit = total_sales - sales_return
    low_stock_items = InventoryItem.objects.filter(quantity__lte=F('reorder_point')).order_by('quantity')[:5]

    today = timezone.now().date()

    expired_batches = ProductBatch.objects.filter(
        expiry_date__isnull=False,
        expiry_date__lte=today, 
        quantity_on_hand__gt=0
    )
    
    for batch in expired_batches:
        batch.quantity_on_hand = 0
        batch.status = 'pulled_out'
        batch.save()

        log_system_activity(
            user=request.user,
            action='AUTO PULL OUT',
            description=f"System automatically pulled out expired batch {batch.batch_code} ({batch.product.item_name})."
        )

    time_window = today + timedelta(days=30) 

    expiring_batches = ProductBatch.objects.filter(
        expiry_date__isnull=False,       
        expiry_date__gte=today,          
        expiry_date__lte=time_window,    
        quantity_on_hand__gt=0           
    ).order_by('expiry_date')[:6]

    metrics = {
        'total_sales': total_sales,
        'sales_return': sales_return,
        'profit': profit,
        'total_purchase': 0.00,
        'purchase_return': 0.00,
        'invoice_due': 0.00,
        'expenses': 0.00,
        'payment_return': 0.00,
    }

    context = {
        'metrics': metrics,
        'low_stock_items': low_stock_items,
        'expiring_batches': expiring_batches, 
        'pending_resets': [], 
        'pending_reset_count': 0,
    }
    return render(request, 'dashboard/dashboard.html', context)

@login_required
def employee_dashboard(request):
    if getattr(request.user, 'role', 'employee') == 'admin' or request.user.is_superuser:
        return redirect('admin_dashboard')
    return redirect('pos:pos_index')

def user_management_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirm_password')
        role = request.POST.get('role')
        full_name = request.POST.get('full_name')

        if not full_name:
            messages.error(request, 'Error: Full Name was missing from the form. Please hard-refresh your browser (Ctrl+F5) and try again.')
            return redirect('user_management')

        if User.objects.filter(username=username).exists():
            messages.error(request, f"The username '{username}' is already taken.")
            return redirect('user_management')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match. Please try again.')
            return redirect('user_management')
        
        if len(password) < 8 or not re.search(r'\d', password) or not re.search(r'[A-Z]', password):
            messages.error(request, 'Password does not meet the security requirements.')
            return redirect('user_management')
            
        new_user = User.objects.create_user(
            username=username, 
            password=password,
            full_name=full_name,
            role=role 
        )
        
        if role == 'Admin':
            new_user.is_staff = True
            new_user.is_superuser = True
        else:
            new_user.is_staff = False
            new_user.is_superuser = False
        
        new_user.save()
        log_system_activity(
            user=request.user,
            action='CREATE USER',
            description=f"Created a new {role} account for {full_name} ({username})."
        )
        messages.success(request, f"Successfully created {role} account for {full_name}.")
        return redirect('user_management')

    users = User.objects.all().order_by('-date_created')

    pending_report_requests = EmployeeProfile.objects.filter(
        reports_access_requested=True, 
        reports_access_approved=False
    )
    pending_reset_requests = EmployeeProfile.objects.filter(
        reset_requested=True, 
        reset_approved_by_admin=False
    )
    pending_settings_requests = EmployeeProfile.objects.filter(
        settings_access_requested=True, 
        settings_access_approved=False
    )
    
    pending_requests = []
    
    for req in pending_reset_requests:
        pending_requests.append({
            'id': req.id,
            'user': req.user,
            'type_label': 'Password Reset',
            'action_url': reverse('security:review_resets'),
            'icon': 'ph-key'
        })
        
    for req in pending_report_requests:
        pending_requests.append({
            'id': req.id,
            'user': req.user,
            'type_label': 'Reports Hub Access',
            'action_url': reverse('security:review_reports_access'),
            'icon': 'ph-chart-pie-slice'
        })

    for req in pending_settings_requests:
        pending_requests.append({
            'id': req.id,
            'user': req.user,
            'type_label': 'General Settings Access',
            'action_url': reverse('security:review_settings_access'),
            'icon': 'ph-gear'
        })

    return render(request, 'dashboard/user_management.html', {
        'users': users,
        'pending_requests': pending_requests
    })

def get_current_db_size():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT round(sum(data_length + index_length) / 1024 / 1024, 2) 
            FROM information_schema.tables 
            WHERE table_schema = 'jbson_dev';
        """)
        result = cursor.fetchone()
        return result[0] if result and result[0] else 0

@login_required
@settings_access_required
def settings_hub_view(request):
    report = []
    with connection.cursor() as cursor:
        cursor.execute('SHOW TABLE STATUS WHERE Data_free > 0')
        tables = cursor.fetchall()
        for table in tables:
            overhead_mb = round(table[11] / 1024 / 1024, 3)
            if overhead_mb > 0:
                report.append(f"Table '{table[0]}' has {overhead_mb} MB overhead.")

    return render(request, 'dashboard/settings_hub.html', {
        'report': report,
        'db_size': get_current_db_size()
    })

@login_required
def delete_user(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, 'Access denied.')
        return redirect('security:register')

    user_to_delete = get_object_or_404(User, id=user_id)
    username = user_to_delete.username
    user_to_delete.delete()
    log_system_activity(
        user=request.user,
        action='DELETE USER',
        description=f"Deleted user account: '{username}'"
    )
    messages.success(request, f"User '{username}' deleted.")
    return redirect('user_management')

def verify_admin_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        password = data.get('password')
        
        if request.user.check_password(password):
            return JsonResponse({'success': True})
        else:
            return JsonResponse({'success': False})
            
    return JsonResponse({'error': 'Invalid request'}, status=400)

@login_required
def edit_user_view(request):
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        user = get_object_or_404(User, id=user_id)
        
        user.full_name = request.POST.get('edit_full_name')
        user.username = request.POST.get('edit_username')
        
        role = request.POST.get('edit_role')
        user.is_superuser = (role == 'Admin')
        user.role = 'admin' if role == 'Admin' else 'employee'
        
        new_pass = request.POST.get('new_password')
        if new_pass:
            user.set_password(new_pass)
            
        user.save()

        # ==========================================
        # GRANULAR PERMISSIONS HANDLING
        # ==========================================
        profile, created = EmployeeProfile.objects.get_or_create(user=user)
        one_hour_from_now = timezone.now() + timedelta(minutes=60)
        
        permissions_map = {
            'grant_dashboard': 'dashboard',
            'grant_inv_products': 'inv_products',
            'grant_inv_categories': 'inv_categories',
            'grant_inv_po': 'inv_po',
            'grant_inv_barcode': 'inv_barcode',
            'grant_sales_checkout': 'sales_checkout',
            'grant_sales_sales': 'sales_sales',
            'grant_sales_invoices': 'sales_invoices',
            'grant_sales_return': 'sales_return',
            'grant_sales_trade_credit': 'sales_trade_credit',
            'grant_sales_quotations': 'sales_quotations',
            'grant_sales_suppliers': 'sales_suppliers',
            'grant_reports': 'reports',
            'grant_um_users': 'um_users',
            'grant_um_activity_logs': 'um_activity_logs',
            'grant_settings': 'settings',
            'grant_user_manual': 'user_manual',
        }

        for post_key, field_prefix in permissions_map.items():
            is_granted = request.POST.get(post_key) == 'on'
            setattr(profile, f'{field_prefix}_access_approved', is_granted)
            setattr(profile, f'{field_prefix}_access_expires_at', one_hour_from_now if is_granted else None)
            
        profile.save()
        # ==========================================

        log_system_activity(
            user=request.user,
            action='EDIT USER',
            description=f"Modified account details/permissions for user '{user.username}'."
        )
        messages.success(request, f'User {user.username} and temporary permissions updated successfully!')
        
    return redirect('user_management')

@login_required
@require_http_methods(['POST'])
def request_reports_access(request):
    if getattr(request.user, 'role', 'employee').lower() == 'employee':
        profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
        profile.reports_access_requested = True
        profile.save()

        admins = User.objects.filter(role='Admin', is_active=True)
        for admin in admins:
            Notification.objects.create(
                user=admin,
                notification_type='access_request',
                priority='medium',
                title='Reports Access Request',
                message=f"Employee '{request.user.username}' is requesting access to the Reports Hub.",
                action_url=reverse('user_management')
            )
        
        log_system_activity(
            user=request.user,
            action='REQUEST REPORTS ACCESS',
            description='Employee requested access to the Reports Hub.'
        )
        messages.success(request, 'Request to access the Reports Hub has been sent to the Admin.')
    return redirect('reports_analytics:reports_hub')

@login_required
@require_http_methods(['POST'])
def review_reports_access(request):
    is_admin = getattr(request.user, 'role', 'employee').lower() == 'admin' or request.user.is_superuser
    if not is_admin:
        return redirect(_role_redirect_url(request.user))
        
    profile_id = request.POST.get('profile_id')
    action = request.POST.get('action')
    
    try:
        profile = EmployeeProfile.objects.get(id=profile_id)
        if action == 'approve':
            profile.reports_access_approved = True
            profile.reports_access_requested = False
            profile.reports_access_expires_at = timezone.now() + timedelta(minutes=60)
            profile.save()
            log_system_activity(
                user=request.user,
                action='APPROVE REPORTS ACCESS',
                description=f"Approved 1-hour reports access for '{profile.user.username}'."
            )
            messages.success(request, f'Reports access granted to {profile.user.full_name} for 1 hour.')
            
            Notification.objects.create(
                user=profile.user,
                notification_type='access_approved',
                priority='high',
                title='Reports Access Approved',
                message='Your request is approved. You have 1 hour of access starting now.',
                action_url=reverse('reports_analytics:reports_hub')
            )
            
        elif action == 'reject':
            profile.reports_access_requested = False
            profile.reports_access_approved = False
            profile.reports_access_expires_at = None
            profile.save()
            log_system_activity(
                user=request.user,
                action='REJECT REPORTS ACCESS',
                description=f"Rejected reports access request for '{profile.user.username}'."
            )
            messages.error(request, f'Reports access denied for {profile.user.full_name}.')
            
    except EmployeeProfile.DoesNotExist:
        messages.error(request, 'Profile not found.')
        
    return redirect('user_management')

@login_required
@require_http_methods(['POST'])
def request_settings_access(request):
    if getattr(request.user, 'role', 'employee').lower() == 'employee':
        profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
        profile.settings_access_requested = True
        profile.save()

        admins = User.objects.filter(role='Admin', is_active=True)
        for admin in admins:
            Notification.objects.create(
                user=admin,
                notification_type='info',
                priority='medium',
                title='General Settings Access Request',
                message=f"Employee '{request.user.username}' is requesting access to General Settings.",
                action_url=reverse('user_management')
            )
        
        log_system_activity(
            user=request.user,
            action='REQUEST SETTINGS ACCESS',
            description='Employee requested access to General Settings.'
        )
        messages.success(request, 'Request to access General Settings has been sent to the Admin.')
    return redirect('settings_hub')

@login_required
@require_http_methods(['POST'])
def review_settings_access(request):
    is_admin = getattr(request.user, 'role', 'employee').lower() == 'admin' or request.user.is_superuser
    if not is_admin:
        return redirect(_role_redirect_url(request.user))
        
    profile_id = request.POST.get('profile_id')
    action = request.POST.get('action')
    
    try:
        profile = EmployeeProfile.objects.get(id=profile_id)
        if action == 'approve':
            profile.settings_access_approved = True
            profile.settings_access_requested = False
            profile.settings_access_expires_at = timezone.now() + timedelta(minutes=60)
            profile.save()
            
            log_system_activity(
                user=request.user,
                action='APPROVE SETTINGS ACCESS',
                description=f"Approved 1-hour settings access for '{profile.user.username}'."
            )
            messages.success(request, f'Settings access granted to {profile.user.full_name} for 1 hour.')
            
            Notification.objects.create(
                user=profile.user,
                notification_type='info',
                priority='high',
                title='Settings Access Approved',
                message='Your request for General Settings is approved. You have 1 hour of access starting now.',
                action_url=reverse('settings_hub')
            )
            
        elif action == 'reject':
            profile.settings_access_requested = False
            profile.settings_access_approved = False
            profile.settings_access_expires_at = None
            profile.save()
            
            log_system_activity(
                user=request.user,
                action='REJECT SETTINGS ACCESS',
                description=f"Rejected settings access request for '{profile.user.username}'."
            )
            messages.error(request, f'Settings access denied for {profile.user.full_name}.')
            
    except EmployeeProfile.DoesNotExist:
        messages.error(request, 'Profile not found.')
        
    return redirect('user_management')