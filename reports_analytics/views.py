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

def sales_report_view(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # 1. Base queries
    transactions = Transaction.objects.filter(status__in=['completed', 'paid', 'credit'])
    returns = SalesReturn.objects.all()

    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        transactions = transactions.filter(date_completed__range=[start_date, end_date])
        returns = returns.filter(created_at__range=[start_date, end_date])

    # --- SUMMARY COMPUTATIONS ---
    summary = transactions.aggregate(
        total_rev=Coalesce(Sum('total_amount'), 0, output_field=DecimalField()),
        total_ord=Count('id')
    )
    gross_rev = summary['total_rev']
    total_ret_amt = returns.aggregate(total=Coalesce(Sum('total_refund'), 0, output_field=DecimalField()))['total']
    net_revenue = gross_rev - total_ret_amt

    # --- PAYMENT METHOD BREAKDOWN (NET) ---
    # Binabawas na natin ang returns dito para accurate ang 'Amount Collected'
    payment_methods = transactions.values('payment_method').annotate(
        gross=Sum('total_amount'),
        refunds=Coalesce(Sum('returns__total_refund'), 0, output_field=DecimalField())
    ).annotate(
        net_collected=F('gross') - F('refunds')
    ).order_by('-net_collected')

    # --- TOP SELLING PRODUCTS (NET) ---
    sold_items = TransactionItem.objects.filter(transaction__in=transactions)
    product_sales = sold_items.values(
        'inventory_item__id', 
        'inventory_item__item_name'
    ).annotate(
        total_sold_qty=Sum('quantity'),
        # Gross subtotal minus any returns for this specific product
        # NOTE: Para maging 100% accurate ito, dapat naka-link ang SalesReturnItem sa product.
        total_sold_amount=Sum('subtotal') 
    ).order_by('-total_sold_amount')[:10]

    # --- ANNOTATE TRANSACTIONS FOR TABLE ---
    transactions = transactions.annotate(
        refunded_amount=Coalesce(Sum('returns__total_refund'), 0, output_field=DecimalField())
    ).annotate(
        adjusted_total=ExpressionWrapper(F('total_amount') - F('refunded_amount'), output_field=DecimalField())
    ).order_by('-date_completed')

    context = {
        'total_revenue': gross_rev,
        'total_returns': total_ret_amt,
        'net_revenue': net_revenue,
        'total_orders': summary['total_ord'],
        'payment_methods': payment_methods,
        'transactions': transactions,
        'product_sales': product_sales,
        'return_logs': returns.order_by('-created_at'),
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    return render(request, 'reports_analytics/sales_report.html', context)

def procurement_report(request):
    # 1. High-Level KPIs
    total_spent = PurchaseOrder.objects.filter(status='received').aggregate(total=Sum('total_amount'))['total'] or 0
    pending_cash = PurchaseOrder.objects.filter(status='pending').aggregate(total=Sum('total_amount'))['total'] or 0
    total_pos = PurchaseOrder.objects.count()
    active_suppliers = Supplier.objects.filter(is_active=True).count()

    # 2. Supplier Leaderboard (Who do we spend the most with?)
    suppliers = Supplier.objects.annotate(
        total_pos=Count('purchase_orders'),
        total_spent=Sum(
            'purchase_orders__total_amount', 
            filter=Q(purchase_orders__status='received')
        )
    ).order_by('-total_spent')

    # 3. Recent Order History
    recent_pos = PurchaseOrder.objects.all().order_by('-order_date')

    return render(request, 'reports_analytics/procurement_report.html', {
        'total_spent': total_spent,
        'pending_cash': pending_cash,
        'total_pos': total_pos,
        'active_suppliers': active_suppliers,
        'suppliers': suppliers,
        'recent_pos': recent_pos
    })