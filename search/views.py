from django.http import JsonResponse
from django.urls import reverse
from django.urls.exceptions import NoReverseMatch
from django.db.models import Q
from inventory.models import InventoryItem, Category, PurchaseOrder, Supplier
from billing_payment.models import Invoice, SalesReturn, Customer
from point_of_sale.models import Transaction
from django.contrib.auth import get_user_model
User = get_user_model()


def global_search_api(request):
    query = request.GET.get('q', '').strip()
    results = []

    if query:
        # 1. NAVIGATION SHORTCUTS
        # 1. NAVIGATION SHORTCUTS
        shortcuts = []

        # Gumawa tayo ng helper function para hindi mag-crash ang buong search kung may isang URL na hindi mahanap
        def add_shortcut(title, url_name, module_name):
            try:
                shortcuts.append({
                    "title": title, 
                    "url": reverse(url_name), 
                    "module": module_name
                })
            except NoReverseMatch:
                pass # I-ignore lang yung item kung wala pa yung URL name na yun sa urls.py mo

        # DASHBOARD
        add_shortcut("Dashboard", "admin_dashboard", "Main")
        add_shortcut("General Settings", "settings_hub", "Settings")

        # INVENTORY
        add_shortcut("Products", "inventory:inventory_list", "Inventory") # O kaya 'inventory:product_list' kung may namespace
        add_shortcut("Categories", "inventory:category_list", "Inventory")
        add_shortcut("Purchase Orders", "inventory:create_po", "Inventory")
        add_shortcut("Generate Barcode", "inventory:generate_barcode_page", "Inventory") # O baka 'inventory:barcode_generate'

        # SALES & BILLING
        add_shortcut("Sales", "billing:sales_list", "Sales")
        add_shortcut("Invoices", "billing:invoice_list", "Sales")
        add_shortcut("Sales Return", "billing:sales_return_list", "Sales")
        add_shortcut("Point Of Sales", "pos:pos_index", "Sales")
        add_shortcut("Trade Credit", "billing:customer_list", "Sales")
        add_shortcut("Quotations", "pos:quotation_list", "Sales")

        # REPORTS
        add_shortcut("Sales Report", "reports_analytics:sales_report", "Reports and Analytics")
        add_shortcut("Purchase Report", "reports_analytics:purchase_report", "Reports and Analytics")
        add_shortcut("Inventory Report", "reports_analytics:inventory_report", "Reports and Analytics")
        add_shortcut("Invoice Report", "reports_analytics:invoice_report", "Reports and Analytics")
        add_shortcut("Procurement Report", "reports_analytics:procurement_report", "Reports and Analytics")
        add_shortcut("Profit & Loss", "reports_analytics:profit_loss_report", "Reports and Analytics")

        # USER MANAGEMENT
        add_shortcut("Users", "user_management", "User Management")
        add_shortcut("Activity Logs", "activity_logs", "User Management")
        add_shortcut("Suppliers", "inventory:supplier_list", "User Management") 
        
        for item in shortcuts:
            if query.lower() in item['title'].lower() or query.lower() in item['module'].lower():
                results.append({
                    "type": "shortcut", "title": item['title'], "url": item['url'],
                    "breadcrumb": item['module']
                })

        # 2. DATABASE QUERIES
        
        # A. PRODUCTS (Inventory) - FIXED FIELD NAMES
        products = InventoryItem.objects.filter(
            Q(item_name__icontains=query) | Q(barcode_id__icontains=query) | Q(product_id__icontains=query) 
        )[:3]
        for prod in products:
            results.append({
                "type": "record", "id": str(prod.product_id), "title": f"Product: {prod.item_name}",
                "detail1": f"Stock: {prod.quantity}", "detail2": f"₱{prod.price}", 
                "status": "In Stock" if prod.quantity > 0 else "Low/Out of Stock",
                "url": f"/inventory/products/" 
            })

        # B. CATEGORIES (Inventory)
        categories = Category.objects.filter(
            Q(name__icontains=query) | Q(prefix__icontains=query)
        )[:2]
        for cat in categories:
            results.append({
                "type": "record", "id": cat.prefix, "title": f"Category: {cat.name}",
                "detail1": f"Prefix: {cat.prefix}", "detail2": "", 
                "status": "Active",
                "url": f"/inventory/categories/"
            })

        # C. PURCHASE ORDERS (Inventory)
        pos = PurchaseOrder.objects.filter(
            Q(po_number__icontains=query) 
        )[:3]
        for po in pos:
            results.append({
                "type": "record", "id": po.po_number, "title": f"PO: {po.po_number}",
                "detail1": f"Date: {po.order_date.strftime('%Y-%m-%d')}", "detail2": f"₱{po.total_amount}", 
                "status": po.status, 
                "url": f"/inventory/purchase-orders/"
            })

        # D. SALES & TRANSACTIONS 
        sales = Transaction.objects.filter( 
            Q(reference_number__icontains=query)
            # Tinanggal ko muna yung Q(customer__icontains=query) in case iba column name mo sa customer
        )[:3]
        for sale in sales:
            results.append({
                "type": "record", "id": sale.reference_number, "title": f"TXN: {sale.reference_number}",
                "detail1": "Transaction", "detail2": f"₱{sale.total}", # Pinalitan ko rin muna ito
                "status": sale.status, 
                "url": f"/billing_payment/sales/" 
            })

        # E. INVOICES
        invoices = Invoice.objects.filter(
            Q(invoice_no__icontains=query) 
        )[:3]
        for inv in invoices:
            results.append({
                "type": "record", "id": inv.invoice_no, "title": f"Invoice: {inv.invoice_no}",
                "detail1": f"Due: {inv.due_date}", "detail2": f"₱{inv.total_amount}", 
                "status": inv.status, 
                "url": f"/billing_payment/invoices/"
            })
            
        # F. SALES RETURNS
        returns = SalesReturn.objects.filter(
            Q(return_id__icontains=query) 
        )[:2]
        for ret in returns:
            results.append({
                "type": "record", "id": ret.return_id, "title": f"Return: {ret.return_id}",
                "detail1": f"Orig TXN: {ret.transaction_id}", "detail2": f"₱{ret.amount}", 
                "status": "Returned",
                "url": f"/billing_payment/sales-return/"
            })

        # G. SUPPLIERS - FIXED FIELD NAMES
        suppliers = Supplier.objects.filter(
            Q(name__icontains=query) | Q(contact_name__icontains=query)
        )[:3]
        for sup in suppliers:
            results.append({
                "type": "record", "id": str(sup.supplier_id), "title": f"Supplier: {sup.name}",
                "detail1": f"Contact: {sup.phone or '--'}", "detail2": sup.email or "", 
                "status": "Active" if sup.is_active else "Inactive",
                "url": f"/inventory/suppliers/"
            })

        # H. TRADE CREDIT ACCOUNTS
        credits = Customer.objects.filter(
            Q(name__icontains=query)
        )[:3]
        for tc in credits:
            results.append({
                "type": "record", "id": tc.name, "title": f"Credit Acct: {tc.name}",
                "detail1": f"Limit: ₱{tc.credit_limit}", "detail2": f"Bal: ₱{tc.credit_balance}", 
                "status": tc.credit_status, 
                "url": f"/billing_payment/trade-credit/"
            })

        # I. QUOTATIONS / DRAFT ORDERS
        quotations = Transaction.objects.filter(
            Q(reference_number__icontains=query)
        )[:3]
        for q in quotations:
            results.append({
                "type": "record", "id": q.reference_number, "title": f"Quote: {q.reference_number}",
                "detail1": f"Date: {q.date}", "detail2": f"₱{q.total_amount}", 
                "status": "Draft",
                "url": f"/point_of_sale/quotations/"
            })

        # J. SYSTEM USERS
        users = User.objects.filter(
            Q(username__icontains=query) | Q(full_name__icontains=query)
        )[:3]
        for u in users:
            role_display = "Admin" if u.is_superuser else "Employee"
            results.append({
                "type": "record", "id": u.username, "title": f"User: {u.get_full_name() or u.username}",
                "detail1": f"Role: {role_display}", "detail2": "", 
                "status": "Active" if u.is_active else "Inactive",
                "url": f"/security/users/"
            })

    return JsonResponse(results, safe=False)