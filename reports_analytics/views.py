from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from django.db.models import Sum, Count, Q
from point_of_sale.models import Transaction, TransactionItem
from inventory.models import Category
from django.utils import timezone
from datetime import datetime
from inventory.models import Supplier, PurchaseOrder
from billing_payment.models import SalesReturn
from django.db.models import Sum, Count, F, ExpressionWrapper, DecimalField
from django.db.models.functions import Coalesce
from inventory.models import PurchaseOrder, PurchaseOrderItem
from billing_payment.models import Invoice
from inventory.models import InventoryItem
from django.core.paginator import Paginator
from reports_analytics.models import Expense
from django.shortcuts import render, redirect
from django.contrib import messages
from activity_log.utils import log_system_activity
from django.db.models import Sum, DecimalField, Q
from django.db.models.functions import TruncMonth, Coalesce
from django.core.paginator import Paginator
from django.shortcuts import render
from datetime import datetime
from django.contrib.auth.decorators import login_required
from security.models import EmployeeProfile
import json

from functools import wraps
from django.shortcuts import render
from security.models import EmployeeProfile
from django.utils import timezone

def reports_access_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        role = getattr(request.user, "role", "employee").lower()
        
        if role == "employee" and not request.user.is_superuser:
            profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
            
            # ---> NEW: Check validity using our 10-minute timer property <---
            if not profile.has_valid_reports_access:
                
                # Check if they *were* approved but their time just expired
                was_expired = False
                if profile.reports_access_approved:
                    # Auto-revoke their permissions in the database
                    profile.reports_access_approved = False
                    profile.reports_access_expires_at = None
                    profile.save()
                    was_expired = True
                
                # Block them and show the request page
                return render(request, 'reports_analytics/reports_access_request.html', {
                    'profile': profile,
                    'was_expired': was_expired # Pass this to the template
                })
                
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@reports_access_required
def sales_report_view(request):
    # 1. Kunin ang dates, search inputs, at tanggalin ang 'None' bug
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    sales_search = request.GET.get('sales_search', '').strip()
    returns_search = request.GET.get('returns_search', '').strip() 

    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    # 2. Base queries
    transactions_qs = Transaction.objects.filter(status__in=['completed', 'paid', 'credit'])
    returns_qs = SalesReturn.objects.all()

    # 3. Date Filtering
    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        transactions_qs = transactions_qs.filter(date_completed__range=[start_date, end_date])
        returns_qs = returns_qs.filter(created_at__range=[start_date, end_date])

    # 4. BACKEND SEARCH FILTER (SALES) -- MAY REFUNDED LOGIC NA
    if sales_search:
        if sales_search.lower() == 'refunded':
            transactions_qs = transactions_qs.filter(
                returns__total_refund__isnull=False
            ).distinct()
        else:
            transactions_qs = transactions_qs.filter(
                Q(transaction_ref__icontains=sales_search) |
                Q(payment_method__icontains=sales_search)
            ).distinct()

    # 5. BACKEND SEARCH FILTER (RETURNS)
    if returns_search:
        returns_qs = returns_qs.filter(
            Q(return_id__icontains=returns_search) |
            Q(transaction__transaction_ref__icontains=returns_search)
        )

    # --- SUMMARY COMPUTATIONS ---
    summary = transactions_qs.aggregate(
        total_rev=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()),
        total_ord=Count('id')
    )
    gross_rev = summary['total_rev']
    total_ret_amt = returns_qs.aggregate(total=Coalesce(Sum('total_refund'), 0, output_field=DecimalField()))['total']
    net_revenue = gross_rev - total_ret_amt

    # --- PAYMENT METHOD BREAKDOWN ---
    payment_methods = transactions_qs.values('payment_method').annotate(
        gross=Sum('total_amount'),
        refunds=Coalesce(Sum('returns__total_refund'), 0, output_field=DecimalField())
    ).annotate(
        net_collected=F('gross') - F('refunds')
    ).order_by('-net_collected')

    # --- TOP SELLING PRODUCTS ---
    sold_items = TransactionItem.objects.filter(transaction__in=transactions_qs)
    product_sales = sold_items.values(
        'inventory_item__id', 
        'inventory_item__item_name'
    ).annotate(
        total_sold_qty=Sum('quantity'),
        total_sold_amount=Sum('subtotal') 
    ).order_by('-total_sold_amount')[:10]

    # --- ANNOTATE & PAGINATE TRANSACTIONS ---
    transactions_final = transactions_qs.annotate(
        refunded_amount=Coalesce(Sum('returns__total_refund'), 0, output_field=DecimalField())
    ).annotate(
        adjusted_total=ExpressionWrapper(F('total_amount') - F('refunded_amount'), output_field=DecimalField())
    ).order_by('-date_completed')

    sales_per_page = request.GET.get('sales_per_page', 10)
    try: sales_per_page = int(sales_per_page)
    except ValueError: sales_per_page = 10

    p_sales_num = request.GET.get('p_sales', 1)
    sales_paginator = Paginator(transactions_final, sales_per_page, orphans=0)
    sales_page = sales_paginator.get_page(p_sales_num)

    # --- PAGINATE RETURNS ---
    returns_final = returns_qs.order_by('-created_at')
    
    returns_per_page = request.GET.get('returns_per_page', 5)
    try: returns_per_page = int(returns_per_page)
    except ValueError: returns_per_page = 5

    p_returns_num = request.GET.get('p_returns', 1)
    returns_paginator = Paginator(returns_final, returns_per_page, orphans=0)
    returns_page = returns_paginator.get_page(p_returns_num)

    context = {
        'total_revenue': gross_rev,
        'total_returns': total_ret_amt,
        'net_revenue': net_revenue,
        'total_orders': summary['total_ord'],
        'payment_methods': payment_methods,
        'transactions': sales_page,
        'return_logs': returns_page,
        'product_sales': product_sales,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'sales_per_page': sales_per_page, 
        'returns_per_page': returns_per_page,
        'sales_search': sales_search,
        'returns_search': returns_search, 
    }
    
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        try:
            log_system_activity(
                user=request.user,
                action="GENERATE REPORT",
                description=f"Generated Sales Report {date_range}"
            )
        except NameError:
            pass

    return render(request, 'reports_analytics/sales_report.html', context)

@reports_access_required
def procurement_report(request):
    # 1. Grab dates and search from the form
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    procurement_search = request.GET.get('procurement_search', '').strip() # <-- KINUHA ANG SEARCH

    # 2. Build the base queries and filters
    po_query = PurchaseOrder.objects.all()
    supplier_po_filter = Q()
    
    if start_date_str:
        start_date = parse_date(start_date_str)
        if start_date:
            po_query = po_query.filter(order_date__gte=datetime.combine(start_date, time.min))
            supplier_po_filter &= Q(purchase_orders__order_date__gte=datetime.combine(start_date, time.min))
            
    if end_date_str:
        end_date = parse_date(end_date_str)
        if end_date:
            po_query = po_query.filter(order_date__lte=datetime.combine(end_date, time.max))
            supplier_po_filter &= Q(purchase_orders__order_date__lte=datetime.combine(end_date, time.max))

    # 3. High-Level KPIs
    total_spent = po_query.filter(status='received').aggregate(total=Sum('total_amount'))['total'] or 0
    pending_cash = po_query.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    total_pos = po_query.count()
    active_suppliers = Supplier.objects.filter(is_active=True).count()

    # 4. Supplier Leaderboard
    suppliers = Supplier.objects.annotate(
        total_pos=Count('purchase_orders', filter=supplier_po_filter),
        total_spent=Sum(
            'purchase_orders__total_amount', 
            filter=supplier_po_filter & Q(purchase_orders__status='received')
        )
    ).order_by('-total_spent')

    # 5. BACKEND SEARCH FILTER (PO Number, Supplier, Status)
    if procurement_search:
        po_query = po_query.filter(
            Q(po_number__icontains=procurement_search) |
            Q(supplier__name__icontains=procurement_search) |
            Q(status__icontains=procurement_search)
        )

    # 6. PAGINATION LOGIC para sa Master Purchase History
    po_per_page = request.GET.get('po_per_page', 10)
    try: po_per_page = int(po_per_page)
    except ValueError: po_per_page = 10

    recent_pos_ordered = po_query.order_by('-order_date')
    page_number = request.GET.get('page', 1)
    
    paginator = Paginator(recent_pos_ordered, po_per_page, orphans=0)
    recent_pos_page = paginator.get_page(page_number)

    return render(request, 'reports_analytics/procurement_report.html', {
        'total_spent': total_spent,
        'pending_cash': pending_cash,
        'total_pos': total_pos,
        'active_suppliers': active_suppliers,
        'suppliers': suppliers,
        'recent_pos': recent_pos_page, # <-- Ipinasa ang paginated na object
        'start_date': start_date_str,
        'end_date': end_date_str,
        'po_per_page': po_per_page,
        'procurement_search': procurement_search, # <-- Ipinasa sa context
    })

@reports_access_required
def purchase_report_view(request):
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    purchase_search = request.GET.get('purchase_search', '').strip() # <-- Kinuha ang search input

    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    purchase_orders_qs = PurchaseOrder.objects.exclude(status__icontains='cancel')

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            purchase_orders_qs = purchase_orders_qs.filter(order_date__range=[start_date, end_date])
        except ValueError:
            pass

    # --- BACKEND SEARCH LOGIC ---
    if purchase_search:
        purchase_orders_qs = purchase_orders_qs.filter(
            Q(po_number__icontains=purchase_search) |
            Q(supplier__name__icontains=purchase_search) |
            Q(status__icontains=purchase_search)  
        )

    # --- TOTAL PURCHASES SUMMARY ---
    summary = purchase_orders_qs.aggregate(
        total_expense=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()),
        total_po_count=Count('id')
    )
    total_expense = summary['total_expense']
    total_po_count = summary['total_po_count']

    # --- SUPPLIER BREAKDOWN ---
    supplier_breakdown = purchase_orders_qs.values('supplier__name').annotate(
        total_spent=Coalesce(Sum('total_amount'), 0, output_field=DecimalField())
    ).order_by('-total_spent')

    # --- TOP PURCHASED PRODUCTS (GINAWANG TOP 5) ---
    purchased_items = PurchaseOrderItem.objects.filter(purchase_order__in=purchase_orders_qs)
    top_purchased_products = purchased_items.values(
        'product__item_name' 
    ).annotate(
        total_qty_bought=Sum('quantity_received'), 
        total_spent_on_item=Sum(F('quantity_received') * F('unit_cost'), output_field=DecimalField())
    ).order_by('-total_spent_on_item')[:5] # <-- Pinalitan ng 5

    # --- PAGINATION LOGIC ---
    po_per_page = request.GET.get('po_per_page', 10)
    try: po_per_page = int(po_per_page)
    except ValueError: po_per_page = 10

    purchase_orders_ordered = purchase_orders_qs.order_by('-order_date')
    page_number = request.GET.get('page', 1)
    
    # Nilagyan ng orphans=0 para strict pagination
    paginator = Paginator(purchase_orders_ordered, po_per_page, orphans=0)
    purchase_orders_page = paginator.get_page(page_number)

    context = {
        'purchase_orders': purchase_orders_page,
        'total_expense': total_expense,
        'total_po_count': total_po_count,
        'supplier_breakdown': supplier_breakdown,
        'top_purchased_products': top_purchased_products,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'po_per_page': po_per_page,
        'purchase_search': purchase_search, # <-- Ipinasa sa context
    }
    
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        try:
            log_system_activity(
                user=request.user,
                action="GENERATE REPORT",
                description=f"Generated Purchase Report {date_range}"
            )
        except NameError: pass
        
    return render(request, 'reports_analytics/purchase_report.html', context)

@reports_access_required
def invoice_report_view(request):
    # 1. Kunin ang dates, search input, at i-strip ang 'None' or empty strings
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    invoice_search = request.GET.get('invoice_search', '').strip() # <-- KINUHA ANG SEARCH

    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    # 2. Base Query
    invoices_qs = Invoice.objects.filter(customer__isnull=False).exclude(status__icontains='cancel')

    # 3. Date Filtering logic
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            invoices_qs = invoices_qs.filter(issue_date__range=[start_date, end_date])
        except ValueError:
            pass

    # 4. BACKEND SEARCH FILTER (MAY PAID/UNPAID LOGIC)
    if invoice_search:
        search_lower = invoice_search.lower()
        if search_lower == 'unpaid':
            invoices_qs = invoices_qs.filter(balance_due__gt=0) # May utang pa
        elif search_lower == 'paid':
            invoices_qs = invoices_qs.filter(balance_due__lte=0) # Bayad na
        else:
            invoices_qs = invoices_qs.filter(
                Q(invoice_no__icontains=invoice_search) |
                Q(customer__name__icontains=invoice_search)
            )

    # 5. Annotations and Metrics
    invoices_qs = invoices_qs.annotate(
        paid_amount=F('total_amount') - F('balance_due')
    )

    summary_data = invoices_qs.aggregate(
        total_inv=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()),
        total_bal=Coalesce(Sum('balance_due'), 0, output_field=DecimalField()),
    )

    summary = {
        'total_invoiced': summary_data['total_inv'],
        'total_paid': summary_data['total_inv'] - summary_data['total_bal'],
        'total_balance': summary_data['total_bal'],
    }

    # 6. PAGINATION LOGIC
    invoice_per_page = request.GET.get('invoice_per_page', 10)
    try: invoice_per_page = int(invoice_per_page)
    except ValueError: invoice_per_page = 10

    # Nilagyan ng orphans=0 para saktong bilang per page
    paginator = Paginator(invoices_qs.order_by('-issue_date'), invoice_per_page, orphans=0)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)

    # 7. Customer breakdown
    customer_breakdown = invoices_qs.values('customer__name').annotate(
        customer_total=Sum('total_amount'),
        customer_due=Sum('balance_due')
    ).order_by('-customer_total')[:10]

    context = {
        'invoices': invoices_page,
        'summary': summary,
        'customer_breakdown': customer_breakdown,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'invoice_per_page': invoice_per_page,
        'invoice_search': invoice_search, # <-- IPINASA SA HTML
    }
    
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        try:
            log_system_activity(
                user=request.user,
                action="GENERATE REPORT",
                description=f"Generated Invoice Report {date_range}"
            )
        except NameError: pass

    return render(request, 'reports_analytics/invoice_report.html', context)

@reports_access_required
def inventory_report_view(request):
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    inv_search = request.GET.get('inv_search', '').strip() # <-- Kinuha ang search input

    # Iwas sa 'None' bug
    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    # 1. Base Query
    products_qs = InventoryItem.objects.all()

    # 2. Date Filter
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            products_qs = products_qs.filter(date_added__range=[start_date, end_date])
        except ValueError:
            pass

    # 3. BACKEND SEARCH FILTER (MAY LOW STOCK LOGIC)
    if inv_search:
        # Kung nag-search sila ng 'low' o 'stock', isasama ng query ang mga low stock items
        if inv_search.lower() in ['low', 'stock', 'low stock']:
            products_qs = products_qs.filter(
                Q(item_name__icontains=inv_search) |
                Q(category__name__icontains=inv_search) |
                Q(quantity__lte=F('reorder_point')) # <-- Hahanapin din ang low stock
            )
        else:
            products_qs = products_qs.filter(
                Q(item_name__icontains=inv_search) |
                Q(category__name__icontains=inv_search)
            )

    # 4. Annotations para sa total value per item
    products_qs = products_qs.annotate(
        total_value=F('quantity') * F('unit_cost')
    )

    # 5. Global Metrics (Base sa filtered query)
    summary_data = products_qs.aggregate(
        total_items=Count('id'),
        total_val=Coalesce(Sum('total_value'), 0, output_field=DecimalField()),
    )
    low_stock_count = products_qs.filter(quantity__lte=F('reorder_point')).count()

    summary = {
        'total_items': summary_data['total_items'],
        'total_valuation': summary_data['total_val'],
        'low_stock_count': low_stock_count
    }

    # 6. PAGINATION LOGIC
    inv_per_page = request.GET.get('inv_per_page', 10)
    try: inv_per_page = int(inv_per_page)
    except ValueError: inv_per_page = 10

    # I-order bago i-paginate
    products_ordered = products_qs.order_by('item_name')
    
    page_number = request.GET.get('page', 1)
    # Orphans=0 para strict ang count per page
    paginator = Paginator(products_ordered, inv_per_page, orphans=0)
    products_page = paginator.get_page(page_number)

    context = {
        'products': products_page, 
        'summary': summary,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'inv_per_page': inv_per_page,
        'inv_search': inv_search, # <-- Ipinasa sa context
    }
    
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        try:
            log_system_activity(
                user=request.user,
                action="GENERATE REPORT",
                description=f"Generated Inventory Valuation Report {date_range}"
            )
        except NameError:
            pass
            
    return render(request, 'reports_analytics/inventory_report.html', context)

@reports_access_required
def profit_loss_report_view(request):
    # --- LOGIC PARA SA PAG-SAVE NG EXPENSE (MODAL POST) ---
    if request.method == 'POST' and 'add_expense' in request.POST:
        expense_date = request.POST.get('expense_date')
        description = request.POST.get('description')
        category = request.POST.get('category')
        amount = request.POST.get('amount')
        
        if expense_date and description and amount:
            try:
                Expense.objects.create(
                    expense_date=expense_date,
                    description=description,
                    category=category,
                    amount=amount
                )
                messages.success(request, 'Expense saved successfully!', extra_tags='expense_success')
                return redirect('reports_analytics:profit_loss_report')
            except Exception as e:
                pass

    # --- KUNIN ANG MGA GET PARAMETERS ---
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    purchase_search = request.GET.get('purchase_search', '').strip()
    expense_search = request.GET.get('expense_search', '').strip()
    
    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    sales_qs = Transaction.objects.filter(status__in=['completed', 'paid'])
    purchase_qs = PurchaseOrder.objects.exclude(status__icontains='cancel')
    opex_qs = Expense.objects.all()

    # --- DATE FILTERS ---
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            sales_qs = sales_qs.filter(date_completed__range=[start_date, end_date])
            purchase_qs = purchase_qs.filter(order_date__range=[start_date, end_date])
            opex_qs = opex_qs.filter(expense_date__range=[start_date, end_date])
        except ValueError: pass

    # --- SEARCH FILTERS (Para gumana sa lahat ng page) ---
    if purchase_search:
        purchase_qs = purchase_qs.filter(
            Q(po_number__icontains=purchase_search) | 
            Q(supplier__name__icontains=purchase_search)
        )
        
    if expense_search:
        opex_qs = opex_qs.filter(
            Q(description__icontains=expense_search) | 
            Q(category__icontains=expense_search)
        )

    # --- TOTALS CALCULATION ---
    total_income = sales_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_purchases = purchase_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_opex = opex_qs.aggregate(total=Coalesce(Sum('amount'), 0, output_field=DecimalField()))['total']
    net_profit = total_income - total_purchases - total_opex

    # --- STRICT PAGINATION ---
    try:
        po_per_page = int(request.GET.get('po_per_page', 5))
    except ValueError:
        po_per_page = 5

    try:
        exp_per_page = int(request.GET.get('exp_per_page', 5))
    except ValueError:
        exp_per_page = 5

    po_paginator = Paginator(purchase_qs.order_by('-order_date'), po_per_page, orphans=0)
    purchases_page = po_paginator.get_page(request.GET.get('po_page', 1))

    exp_paginator = Paginator(opex_qs.order_by('-expense_date'), exp_per_page, orphans=0)
    expenses_page = exp_paginator.get_page(request.GET.get('exp_page', 1))

    context = {
        'total_income': total_income,
        'total_purchases': total_purchases,
        'total_opex': total_opex,
        'net_profit': net_profit,
        'purchases': purchases_page,
        'expenses': expenses_page,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'po_per_page': po_per_page,
        'exp_per_page': exp_per_page,
        'purchase_search': purchase_search,
        'expense_search': expense_search,
    }
    return render(request, 'reports_analytics/profit_loss_report.html', context)

@reports_access_required
def annual_report_view(request):
    # 1. Kunin ang filters
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    annual_search = request.GET.get('annual_search', '').strip()

    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    # 2. Base Queries mula sa lahat ng tables
    sales_qs = Transaction.objects.filter(status__in=['completed', 'paid'])
    purchases_qs = PurchaseOrder.objects.exclude(status__icontains='cancel')
    expenses_qs = Expense.objects.all()

    # 3. Date Filtering
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            sales_qs = sales_qs.filter(date_completed__range=[start_date, end_date])
            purchases_qs = purchases_qs.filter(order_date__range=[start_date, end_date])
            expenses_qs = expenses_qs.filter(expense_date__range=[start_date, end_date])
        except ValueError:
            pass

    # 4. Global Metrics & EXECUTIVE SUMMARY MATH
    total_sales = sales_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_purchases = purchases_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_opex = expenses_qs.aggregate(total=Coalesce(Sum('amount'), 0, output_field=DecimalField()))['total']
    net_profit = total_sales - total_purchases - total_opex

    total_expenses_combined = total_purchases + total_opex
    profit_margin = (net_profit / total_sales * 100) if total_sales > 0 else 0
    expense_ratio = (total_expenses_combined / total_sales * 100) if total_sales > 0 else 0

    # 5. Group Data by Month (Manual Grouping para iwas MySQL Error)
    monthly_data = {}

    def process_qs(qs, date_attr, amount_attr, key_name):
        for item in qs:
            d = getattr(item, date_attr)
            if d:
                sort_key = d.strftime('%Y-%m') # Ex. 2026-05
                display_name = d.strftime('%B %Y') # Ex. May 2026
                
                if sort_key not in monthly_data:
                    monthly_data[sort_key] = {
                        'month_name': display_name, 
                        'sales': 0, 
                        'purchases': 0, 
                        'expenses': 0
                    }
                
                amount = getattr(item, amount_attr) or 0
                monthly_data[sort_key][key_name] += float(amount)

    process_qs(sales_qs, 'date_completed', 'total_amount', 'sales')
    process_qs(purchases_qs, 'order_date', 'total_amount', 'purchases')
    process_qs(expenses_qs, 'expense_date', 'amount', 'expenses')

    # 6. Compute Profit per Month
    final_monthly_data = []
    
    for sort_key in sorted(monthly_data.keys()):
        data = monthly_data[sort_key]
        m_sales = data['sales']
        m_purch = data['purchases']
        m_exp = data['expenses']
        m_profit = m_sales - m_purch - m_exp
        month_name = data['month_name']

        if annual_search and annual_search.lower() not in month_name.lower():
            continue

        final_monthly_data.append({
            'month': month_name,
            'sales': m_sales,
            'purchases': m_purch,
            'expenses': m_exp,
            'profit': m_profit
        })

    # 7. Extract data para sa Chart.js
    chart_labels = [d['month'] for d in final_monthly_data]
    chart_sales = [d['sales'] for d in final_monthly_data]
    chart_expenses = [d['purchases'] + d['expenses'] for d in final_monthly_data]
    chart_profit = [d['profit'] for d in final_monthly_data]

    # 8. PAGINATION LOGIC
    annual_per_page = request.GET.get('annual_per_page', 6)
    try: annual_per_page = int(annual_per_page)
    except ValueError: annual_per_page = 6

    page_number = request.GET.get('page', 1)
    paginator = Paginator(list(reversed(final_monthly_data)), annual_per_page, orphans=0)
    monthly_records_page = paginator.get_page(page_number)

    context = {
        'total_sales': total_sales,
        'total_purchases': total_purchases,
        'total_opex': total_opex,
        'net_profit': net_profit,
        
        # Dagdag para sa Executive Summary
        'total_expenses_combined': total_expenses_combined,
        'profit_margin': profit_margin,
        'expense_ratio': expense_ratio,
        
        'monthly_records': monthly_records_page,
        
        # JSON dumps para mabasa ng JS
        'chart_labels': json.dumps(chart_labels),
        'chart_sales': json.dumps(chart_sales),
        'chart_expenses': json.dumps(chart_expenses),
        'chart_profit': json.dumps(chart_profit),
        
        'start_date': start_date_str,
        'end_date': end_date_str,
        'annual_search': annual_search,
        'annual_per_page': annual_per_page,
    }
    
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        try:
            log_system_activity(
                user=request.user,
                action="GENERATE REPORT",
                description=f"Generated Annual Report {date_range}"
            )
        except NameError:
            pass

    return render(request, 'reports_analytics/annual_report.html', context)


@login_required
@reports_access_required
def reports_hub(request):
    """Main hub para sa lahat ng reports."""
    
    # Check if the user is an employee and if they have approval
    if getattr(request.user, "role", "employee") == "employee":
        profile, created = EmployeeProfile.objects.get_or_create(user=request.user)
            
    return render(request, 'reports_analytics/reports_hub.html')