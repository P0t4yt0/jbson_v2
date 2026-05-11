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

def sales_report_view(request):
    # 1. Kunin ang dates at tanggalin ang 'None' bug
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

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

    # DYNAMIC ROWS PER PAGE LOGIC (SALES)
    sales_per_page = request.GET.get('sales_per_page', 10)
    try: sales_per_page = int(sales_per_page)
    except ValueError: sales_per_page = 10

    p_sales_num = request.GET.get('p_sales', 1)
    sales_paginator = Paginator(transactions_final, sales_per_page)
    sales_page = sales_paginator.get_page(p_sales_num)

    # --- PAGINATE RETURNS ---
    returns_final = returns_qs.order_by('-created_at')
    
    # DYNAMIC ROWS PER PAGE LOGIC (RETURNS)
    returns_per_page = request.GET.get('returns_per_page', 5)
    try: returns_per_page = int(returns_per_page)
    except ValueError: returns_per_page = 5

    p_returns_num = request.GET.get('p_returns', 1)
    returns_paginator = Paginator(returns_final, returns_per_page)
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
    }
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        log_system_activity(
            user=request.user,
            action="GENERATE REPORT",
            description=f"Generated Sales Report {date_range}"
        )
    return render(request, 'reports_analytics/sales_report.html', context)

def procurement_report(request):
    # 1. Grab dates from the form
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    # 2. Build the base queries and filters
    po_query = PurchaseOrder.objects.all()
    supplier_po_filter = Q() # This helps us filter the supplier math
    
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

    # 3. High-Level KPIs (Now filtered by date!)
    total_spent = po_query.filter(status='received').aggregate(total=Sum('total_amount'))['total'] or 0
    pending_cash = po_query.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    total_pos = po_query.count()
    active_suppliers = Supplier.objects.filter(is_active=True).count()

    # 4. Supplier Leaderboard (Now calculates totals based only on the selected dates!)
    suppliers = Supplier.objects.annotate(
        total_pos=Count('purchase_orders', filter=supplier_po_filter),
        total_spent=Sum(
            'purchase_orders__total_amount', 
            filter=supplier_po_filter & Q(purchase_orders__status='received')
        )
    ).order_by('-total_spent')

    # 5. Recent Order History (Filtered by date)
    recent_pos = po_query.order_by('-order_date')

    return render(request, 'reports_analytics/procurement_report.html', {
        'total_spent': total_spent,
        'pending_cash': pending_cash,
        'total_pos': total_pos,
        'active_suppliers': active_suppliers,
        'suppliers': suppliers,
        'recent_pos': recent_pos,
        'start_date': start_date_str, # Send back to template
        'end_date': end_date_str,     # Send back to template
    })

def purchase_report_view(request):
    # 1. Kunin ang dates at tanggalin ang 'None' bug
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    # 2. Base query
    purchase_orders_qs = PurchaseOrder.objects.exclude(status__icontains='cancel')

    # 3. Date Filtering
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            purchase_orders_qs = purchase_orders_qs.filter(order_date__range=[start_date, end_date])
        except ValueError:
            # Kung sakaling may maling format na pumasok, wag mag-filter
            pass

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

    # --- TOP PURCHASED PRODUCTS ---
    purchased_items = PurchaseOrderItem.objects.filter(purchase_order__in=purchase_orders_qs)
    top_purchased_products = purchased_items.values(
        'product__item_name' 
    ).annotate(
        total_qty_bought=Sum('quantity_received'), 
        total_spent_on_item=Sum(F('quantity_received') * F('unit_cost'), output_field=DecimalField())
    ).order_by('-total_spent_on_item')[:10]

    # --- PAGINATION LOGIC ---
    # Kunin ang per page preference
    po_per_page = request.GET.get('po_per_page', 10)
    try:
        po_per_page = int(po_per_page)
    except ValueError:
        po_per_page = 10

    # I-order bago i-paginate
    purchase_orders_ordered = purchase_orders_qs.order_by('-order_date')
    
    page_number = request.GET.get('page', 1)
    paginator = Paginator(purchase_orders_ordered, po_per_page)
    purchase_orders_page = paginator.get_page(page_number)

    context = {
        'purchase_orders': purchase_orders_page, # Ito na yung may pagination
        'total_expense': total_expense,
        'total_po_count': total_po_count,
        'supplier_breakdown': supplier_breakdown,
        'top_purchased_products': top_purchased_products,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'po_per_page': po_per_page,
    }
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        log_system_activity(
            user=request.user,
            action="GENERATE REPORT",
            description=f"Generated Purchase Report {date_range}"
        )
    return render(request, 'reports_analytics/purchase_report.html', context)

def invoice_report_view(request):
    # 1. Kunin ang dates at i-strip ang 'None' or empty strings
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

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

    # 4. Annotations and Metrics
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

    # 5. PAGINATION LOGIC
    invoice_per_page = request.GET.get('invoice_per_page', 10)
    try:
        invoice_per_page = int(invoice_per_page)
    except ValueError:
        invoice_per_page = 10

    paginator = Paginator(invoices_qs.order_by('-issue_date'), invoice_per_page)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)

    # 6. Customer breakdown
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
    }
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        log_system_activity(
            user=request.user,
            action="GENERATE REPORT",
            description=f"Generated Invoice Report {date_range}"
        )
    return render(request, 'reports_analytics/invoice_report.html', context)

def inventory_report_view(request):
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

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

    # 3. Annotations para sa total value per item
    products_qs = products_qs.annotate(
        total_value=F('quantity') * F('unit_cost')
    )

    # 4. Global Metrics (Base sa filtered query)
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

    # 5. PAGINATION LOGIC
    inv_per_page = request.GET.get('inv_per_page', 10)
    try: inv_per_page = int(inv_per_page)
    except ValueError: inv_per_page = 10

    # I-order bago i-paginate
    products_ordered = products_qs.order_by('item_name')
    
    page_number = request.GET.get('page', 1)
    paginator = Paginator(products_ordered, inv_per_page)
    products_page = paginator.get_page(page_number)

    context = {
        'products': products_page, # Ito na ang may pagination
        'summary': summary,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'inv_per_page': inv_per_page,
    }
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        log_system_activity(
            user=request.user,
            action="GENERATE REPORT",
            description=f"Generated Inventory Valuation Report {date_range}"
        )
    return render(request, 'reports_analytics/inventory_report.html', context)

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
                log_system_activity(
                    user=request.user,
                    action="ADD EXPENSE",
                    description=f"Recorded operating expense: '{description}' (Amount: ₱{amount})"
                )
                # Success Message para sa SweetAlert
                messages.success(request, 'Expense saved successfully!', extra_tags='expense_success')
                return redirect('reports_analytics:profit_loss_report')
            except Exception as e:
                pass

    # --- EXISTING REPORT LOGIC ---
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    
    if start_date_str == 'None': start_date_str = ''
    if end_date_str == 'None': end_date_str = ''

    sales_qs = Transaction.objects.filter(status__in=['completed', 'paid'])
    purchase_qs = PurchaseOrder.objects.exclude(status__icontains='cancel')
    opex_qs = Expense.objects.all()

    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            sales_qs = sales_qs.filter(date_completed__range=[start_date, end_date])
            purchase_qs = purchase_qs.filter(order_date__range=[start_date, end_date])
            opex_qs = opex_qs.filter(expense_date__range=[start_date, end_date])
        except ValueError: pass

    total_income = sales_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_purchases = purchase_qs.aggregate(total=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()))['total']
    total_opex = opex_qs.aggregate(total=Coalesce(Sum('amount'), 0, output_field=DecimalField()))['total']
    net_profit = total_income - total_purchases - total_opex

    po_per_page = request.GET.get('po_per_page', 5)
    po_paginator = Paginator(purchase_qs.order_by('-order_date'), int(po_per_page))
    purchases_page = po_paginator.get_page(request.GET.get('po_page', 1))

    exp_per_page = request.GET.get('exp_per_page', 5)
    exp_paginator = Paginator(opex_qs.order_by('-expense_date'), int(exp_per_page))
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
    }
    if 'is_generating' in request.GET:
        date_range = f"from {start_date_str} to {end_date_str}" if start_date_str and end_date_str else "(All Time)"
        log_system_activity(
            user=request.user,
            action="GENERATE REPORT",
            description=f"Generated Profit & Loss Report {date_range}"
        )
    return render(request, 'reports_analytics/profit_loss_report.html', context)