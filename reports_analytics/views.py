from django.shortcuts import render

# Create your views here.
from django.shortcuts import render
from django.db.models import Sum, Count
from point_of_sale.models import Transaction, TransactionItem
from inventory.models import Category
from django.utils import timezone
from datetime import datetime

def sales_report_view(request):
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    # 1. Kunin lahat ng completed transactions
    transactions = Transaction.objects.filter(status__in=['completed', 'paid', 'credit'])

    if start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        transactions = transactions.filter(date_completed__range=[start_date, end_date])

    # --- REQUIREMENT 1: TOTAL GROSS SALES ---
    summary = transactions.aggregate(
        total_revenue=Sum('total_amount'),
        total_orders=Count('id')
    )
    total_rev = summary['total_revenue'] or 0
    total_ord = summary['total_orders'] or 0

    # --- REQUIREMENT 2: PAYMENT METHOD BREAKDOWN ---
    # I-group ang benta base sa mode of payment (Cash, Online Bank, etc.)
    payment_methods = transactions.values('payment_method').annotate(
        total_collected=Sum('total_amount')
    ).order_by('-total_collected')

    # --- REQUIREMENT 4: TOP SELLING PRODUCTS ---
    sold_items = TransactionItem.objects.filter(transaction__in=transactions)
    product_sales = sold_items.values(
        'inventory_item__product_id', 
        'inventory_item__item_name'
    ).annotate(
        total_sold_qty=Sum('quantity'),
        total_sold_amount=Sum('subtotal')
    ).order_by('-total_sold_amount')[:10] # Kukunin lang natin ang Top 10 para di sobrang haba

    context = {
        'total_revenue': total_rev,
        'total_orders': total_ord,
        'payment_methods': payment_methods,      # BAGONG DATA
        'transactions': transactions.order_by('-date_completed'), # BAGONG DATA (Resibo)
        'product_sales': product_sales,
        'start_date': start_date_str,
        'end_date': end_date_str,
    }
    return render(request, 'reports_analytics/sales_report.html', context)