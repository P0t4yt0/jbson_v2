from django.http import JsonResponse
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.db.models import Q
from inventory.models import InventoryItem, Category, PurchaseOrder, Supplier
from billing_payment.models import Invoice, SalesReturn, Customer
from point_of_sale.models import Transaction
from user_manual.models import ManualArticle
from django.contrib.auth import get_user_model
from security.models import EmployeeProfile

User = get_user_model()

def global_search_api(request):
    query = request.GET.get('q', '').strip()
    results = []

    if query:
        # Kunin ang profile kung Employee siya
        is_admin = getattr(request.user, 'role', '').lower() == 'admin' or request.user.is_superuser
        profile = None
        if not is_admin and request.user.is_authenticated:
            profile, _ = EmployeeProfile.objects.get_or_create(user=request.user)

        shortcuts = []

        def add_shortcut(title, url_name, module_name, condition=True):
            # Idadagdag lang kung True yung condition (or admin)
            if is_admin or condition:
                try:
                    shortcuts.append({
                        "title": title, 
                        "url": reverse(url_name), 
                        "module": module_name
                    })
                except NoReverseMatch:
                    pass

# ==========================================
        # DEFAULT SHORTCUTS (Laging True sa Employee)
        # ==========================================
        
        dashboard_target = "admin_dashboard" if is_admin else "employee_dashboard"
        add_shortcut("Dashboard", dashboard_target, "Main", True) 
        
        add_shortcut("Products", "inventory:inventory_list", "Inventory", True)
        add_shortcut("Categories", "inventory:category_list", "Inventory", True)
        
        if not is_admin:
            add_shortcut("Checkout", "pos:pos_index", "Sales", True)
        
        add_shortcut("Sales Record", "billing:sales_list", "Sales", True)
        add_shortcut("Sales Return", "billing:sales_return_list", "Sales", True)
        add_shortcut("Quotations", "pos:quotation_list", "Sales", True)

        
        add_shortcut("User Manual Hub", "user_manual:hub", "Help & Guides", True)
        add_shortcut("Dashboard Guide", "user_manual:dashboard", "Help & Guides", True)
        add_shortcut("Inventory Guide", "user_manual:inventory", "Help & Guides", True)
        add_shortcut("POS Guide", "user_manual:pos", "Help & Guides", True)
        add_shortcut("Billing Guide", "user_manual:billing", "Help & Guides", True)
        add_shortcut("Reports Guide", "user_manual:reports", "Help & Guides", True)
        add_shortcut("Management Guide", "user_manual:management", "Help & Guides", True)
        add_shortcut("Settings Guide", "user_manual:settings", "Help & Guides", True)
        
        # ==========================================
        # CONDITIONAL SHORTCUTS (1-Hour Temporary Access)
        # ==========================================
        p = profile # shortcut variable lang
        add_shortcut("General Settings", "settings_hub", "Settings", getattr(p, 'has_valid_settings_access', False))
        add_shortcut("Purchase Orders", "inventory:create_po", "Inventory", getattr(p, 'has_inv_po_access', False))
        add_shortcut("Generate Barcode", "inventory:generate_barcode_page", "Inventory", getattr(p, 'has_inv_barcode_access', False))
        add_shortcut("Invoices", "billing:invoice_list", "Sales", getattr(p, 'has_sales_invoices_access', False))
        add_shortcut("Trade Credit", "billing:customer_list", "Sales", getattr(p, 'has_sales_trade_credit_access', False))

        has_reports = getattr(p, 'has_valid_reports_access', False)
        add_shortcut("Sales Report", "reports_analytics:sales_report", "Reports and Analytics", has_reports)
        add_shortcut("Purchase Report", "reports_analytics:purchase_report", "Reports and Analytics", has_reports)
        add_shortcut("Inventory Report", "reports_analytics:inventory_report", "Reports and Analytics", has_reports)
        add_shortcut("Invoice Report", "reports_analytics:invoice_report", "Reports and Analytics", has_reports)
        add_shortcut("Procurement Report", "reports_analytics:procurement_report", "Reports and Analytics", has_reports)
        add_shortcut("Profit & Loss", "reports_analytics:profit_loss_report", "Reports and Analytics", has_reports)

        add_shortcut("Users", "user_management", "User Management", getattr(p, 'has_um_users_access', False))
        add_shortcut("Activity Logs", "activity_logs", "User Management", getattr(p, 'has_um_activity_logs_access', False))
        add_shortcut("Suppliers", "inventory:supplier_list", "User Management", getattr(p, 'has_sales_suppliers_access', False)) 
        
        for item in shortcuts:
            if query.lower() in item['title'].lower() or query.lower() in item['module'].lower():
                results.append({
                    "type": "shortcut", 
                    "title": item['title'], 
                    "url": item['url'],
                    "breadcrumb": item['module']
                })

        # ==========================================
        # DATABASE RECORDS SEARCH 
        # ==========================================

        # Laging may access ang employee sa Products
        products = InventoryItem.objects.filter(
            Q(item_name__icontains=query) | Q(barcode_id__icontains=query) | Q(product_id__icontains=query) 
        )[:3]
        for prod in products:
            results.append({
                "type": "record", 
                "id": str(prod.product_id), 
                "title": f"Product: {prod.item_name}",
                "detail1": f"Stock: {prod.quantity}", 
                "detail2": f"₱{prod.price}", 
                "status": "In Stock" if prod.quantity > 0 else "Low/Out of Stock",
                "url": "/inventory/products/" 
            })

        # Laging may access ang employee sa Categories
        categories = Category.objects.filter(
            Q(name__icontains=query) | Q(prefix__icontains=query)
        )[:2]
        for cat in categories:
            results.append({
                "type": "record", 
                "id": cat.prefix, 
                "title": f"Category: {cat.name}",
                "detail1": f"Prefix: {cat.prefix}", 
                "detail2": "", 
                "status": "Active",
                "url": "/inventory/categories/"
            })

        # Laging may access ang employee sa User Manual
        articles = ManualArticle.objects.filter(
            Q(title__icontains=query) | Q(content__icontains=query),
            is_active=True
        )[:3]
        for article in articles:
            section_name = article.section.title.lower()
            try:
                if 'inventory' in section_name:
                    target_url = reverse('user_manual:inventory') 
                elif 'pos' in section_name:
                    target_url = reverse('user_manual:pos')
                elif 'billing' in section_name:
                    target_url = reverse('user_manual:billing')
                elif 'report' in section_name:
                    target_url = reverse('user_manual:reports')
                elif 'manage' in section_name or 'user' in section_name:
                    target_url = reverse('user_manual:management')
                elif 'setting' in section_name:
                    target_url = reverse('user_manual:settings')
                elif 'dashboard' in section_name:
                    target_url = reverse('user_manual:dashboard')
                else:
                    target_url = reverse('user_manual:hub')
            except NoReverseMatch:
                target_url = "#"

            results.append({
                "type": "record", 
                "id": str(article.id), 
                "title": f"Help Article: {article.title}",
                "detail1": f"Section: {article.section.title}", 
                "detail2": f"Type: {article.section.get_section_type_display()}", 
                "status": "Guide",
                "url": target_url 
            })

        # --- CONDITIONAL DATABASE SEARCHES ---

        # Conditionally search POs
        if is_admin or getattr(p, 'has_inv_po_access', False):
            pos = PurchaseOrder.objects.filter(Q(po_number__icontains=query))[:3]
            for po in pos:
                results.append({
                    "type": "record", 
                    "id": po.po_number, 
                    "title": f"PO: {po.po_number}",
                    "detail1": f"Date: {po.order_date.strftime('%Y-%m-%d')}", 
                    "detail2": f"₱{po.total_amount}", 
                    "status": po.status, 
                    "url": "/inventory/purchase-orders/"
                })

        # Conditionally search Suppliers
        if is_admin or getattr(p, 'has_sales_suppliers_access', False):
            suppliers = Supplier.objects.filter(
                Q(name__icontains=query) | Q(contact_name__icontains=query)
            )[:3]
            for sup in suppliers:
                results.append({
                    "type": "record", 
                    "id": str(sup.supplier_id), 
                    "title": f"Supplier: {sup.name}",
                    "detail1": f"Contact: {sup.phone or '--'}", 
                    "detail2": sup.email or "", 
                    "status": "Active" if sup.is_active else "Inactive",
                    "url": "/inventory/suppliers/"
                })

        # Conditionally search Transactions
        if is_admin or getattr(p, 'has_sales_sales_access', False):
            transactions = Transaction.objects.filter(Q(reference_number__icontains=query))[:3]
            for txn in transactions:
                results.append({
                    "type": "record", 
                    "id": txn.reference_number, 
                    "title": f"TXN: {txn.reference_number}",
                    "detail1": "Transaction", 
                    "detail2": f"₱{txn.total}", 
                    "status": txn.status, 
                    "url": "/billing_payment/sales/" 
                })

        # Conditionally search Invoices
        if is_admin or getattr(p, 'has_sales_invoices_access', False):
            invoices = Invoice.objects.filter(Q(invoice_no__icontains=query))[:3]
            for inv in invoices:
                results.append({
                    "type": "record", 
                    "id": inv.invoice_no, 
                    "title": f"Invoice: {inv.invoice_no}",
                    "detail1": f"Due: {inv.due_date}", 
                    "detail2": f"₱{inv.total_amount}", 
                    "status": inv.status, 
                    "url": "/billing_payment/invoices/"
                })
            
        # Conditionally search Sales Return
        if is_admin or getattr(p, 'has_sales_return_access', False):
            returns = SalesReturn.objects.filter(Q(return_id__icontains=query))[:2]
            for ret in returns:
                results.append({
                    "type": "record", 
                    "id": ret.return_id, 
                    "title": f"Return: {ret.return_id}",
                    "detail1": f"Orig TXN: {ret.transaction_id}", 
                    "detail2": f"₱{ret.amount}", 
                    "status": "Returned",
                    "url": "/billing_payment/sales-return/"
                })

        # Conditionally search Trade Credits
        if is_admin or getattr(p, 'has_sales_trade_credit_access', False):
            credits = Customer.objects.filter(Q(name__icontains=query))[:3]
            for tc in credits:
                results.append({
                    "type": "record", 
                    "id": tc.name, 
                    "title": f"Credit Acct: {tc.name}",
                    "detail1": f"Limit: ₱{tc.credit_limit}", 
                    "detail2": f"Bal: ₱{tc.credit_balance}", 
                    "status": tc.credit_status, 
                    "url": "/billing_payment/trade-credit/"
                })

        # Conditionally search Users
        if is_admin or getattr(p, 'has_um_users_access', False):
            users = User.objects.filter(
                Q(username__icontains=query) | Q(full_name__icontains=query)
            )[:3]
            for u in users:
                role_display = "Admin" if u.is_superuser else "Employee"
                results.append({
                    "type": "record", 
                    "id": u.username, 
                    "title": f"User: {u.get_full_name() or u.username}",
                    "detail1": f"Role: {role_display}", 
                    "detail2": "", 
                    "status": "Active" if u.is_active else "Inactive",
                    "url": "/security/users/"
                })

    return JsonResponse(results, safe=False)