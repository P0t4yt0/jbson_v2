from .models import EmployeeProfile

def admin_notifications(request):
    if getattr(request.user, 'role', '').lower() == 'admin' or request.user.is_superuser: 
        pending_resets = EmployeeProfile.objects.filter(reset_requested=True)
        count = pending_resets.count()
        return {
            'pending_resets': pending_resets,
            'pending_reset_count': count
        }
    return {}

def employee_sidebar_access(request):
    if not request.user.is_authenticated:
        return {}
        
    user_role = getattr(request.user, 'role', '').lower()

    # Kung admin ang naka-login, automatic True lahat ng access
    if user_role == 'admin' or request.user.is_superuser:
        return {
            'show_dashboard': True,
            'show_inv_products': True,
            'show_inv_categories': True,
            'show_inv_po': True,
            'show_inv_barcode': True,
            'show_sales_checkout': True,
            'show_sales_sales': True,
            'show_sales_invoices': True,
            'show_sales_return': True,
            'show_sales_trade_credit': True,
            'show_sales_quotations': True,
            'show_sales_suppliers': True,
            'show_reports': True,
            'show_um_users': True,
            'show_um_activity_logs': True,
            'show_settings': True,
            'show_user_manual': True,
        }
        
    # Kung employee, naka-hardcode as TRUE ang mga DEFAULTS!
    if user_role == 'employee':
        profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
        return {
            # --- DEFAULT MENUS (Laging True) ---
            'show_dashboard': True,
            'show_inv_products': True,
            'show_inv_categories': True,
            'show_sales_checkout': True,
            'show_user_manual': True,
            'show_sales_sales': True,
            'show_sales_return': True,
            'show_sales_quotations': True,

            # --- 1-HOUR TEMPORARY MENUS ---
            'show_inv_po': profile.has_inv_po_access,
            'show_inv_barcode': profile.has_inv_barcode_access,
            'show_sales_invoices': profile.has_sales_invoices_access,
            'show_sales_trade_credit': profile.has_sales_trade_credit_access,
            'show_sales_suppliers': profile.has_sales_suppliers_access,
            'show_reports': profile.has_valid_reports_access,
            'show_um_users': profile.has_um_users_access, 
            'show_um_activity_logs': profile.has_um_activity_logs_access,
            'show_settings': profile.has_valid_settings_access,
        }
    
    return {}