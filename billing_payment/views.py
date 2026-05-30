from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q
from django.core.paginator import Paginator
from django.db import transaction
from decimal import Decimal
import uuid

# Siguraduhing tama ang mga imports base sa folder structure mo
from .models import Customer, Invoice, InvoicePayment, SalesReturn, SalesReturnItem
from point_of_sale.models import Transaction
from inventory.models import InventoryItem
from activity_log.utils import log_system_activity

def customer_list(request):
    # Handle Adding a New Customer
    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        limit = request.POST.get('credit_limit')
        terms = request.POST.get('payment_terms')
        
        if Customer.objects.filter(name=name).exists():
            messages.error(request, f"A customer named {name} already exists.")
        else:
            Customer.objects.create(
                name=name,
                phone=phone,
                is_credit_customer=True,
                credit_limit=limit,
                payment_terms=terms,
                credit_status='active'
            )
            log_system_activity(
                user=request.user,
                action="NEW CUSTOMER",
                description=f"Added new credit customer: '{name}'"
            )
            messages.success(request, f"Customer '{name}' added successfully.")
        return redirect('billing_payment:customer_list')

    # --- GET REQUEST (SEARCH, FILTER, PAGINATION) ---
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    per_page = request.GET.get('per_page', 10)

    # 1. Base Query
    customers = Customer.objects.all().order_by('-credit_balance')
    
    # 2. Search Filter (Customer Name o Contact)
    if search_query:
        customers = customers.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    
    # 3. Status Filter
    if status_filter:
        customers = customers.filter(credit_status__iexact=status_filter)
        
    # 4. Pagination Setup
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(customers, per_page)
    page_number = request.GET.get('page', 1)
    customers_page = paginator.get_page(page_number)
    
    # 5. I-pass sa context
    return render(request, 'billing_payment/customer_list.html', {
        'customers': customers_page,
        'search_query': search_query,
        'status_filter': status_filter,
        'per_page': per_page,
    })

def customer_ledger(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    
    # Get all invoices for this customer, newest first
    invoices = customer.invoices.all().order_by('-issue_date', '-id')
    
    return render(request, 'billing_payment/customer_ledger.html', {
        'customer': customer,
        'invoices': invoices
    })

def get_payment_history_json(request, invoice_id):
    """API endpoint para ibalik ang payment history ng isang invoice sa JSON format"""
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    
    # FIX 1: Pinalitan ang '-payment_date' ng '-date'
    if hasattr(invoice, 'payments'):
        payments_queryset = invoice.payments.all().order_by('-date')
    else:
        payments_queryset = invoice.invoicepayment_set.all().order_by('-date')
    
    payments_data = []
    for p in payments_queryset:
        payments_data.append({
            'amount': float(p.amount), 
            # FIX 2: Pinalitan ang p.payment_date ng p.date
            'date': p.date.strftime("%b %d, %Y"), 
            'method': p.method.capitalize() 
        })
        
    return JsonResponse({
        'status': 'success',
        'invoice_no': invoice.invoice_no,
        'payments': payments_data
    })

def pay_invoice(request, invoice_id):
    if request.method == 'POST':
        invoice = get_object_or_404(Invoice, id=invoice_id)
        
        try:
            amount = Decimal(request.POST.get('amount', '0'))
        except:
            amount = Decimal('0')
            
        method = request.POST.get('method', 'cash')

        # Safety Check: Don't allow overpaying or negative payments
        if amount <= 0 or amount > invoice.balance_due:
            messages.error(request, f"Invalid payment amount. You can only pay up to ₱{invoice.balance_due}.")
            return redirect('billing_payment:customer_ledger', pk=invoice.customer.id)

        # Create the Payment! 
        InvoicePayment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            processed_by=request.user if request.user.is_authenticated else None
        )
        log_system_activity(
            user=request.user,
            action="PAYMENT RECEIVED",
            description=f"Received payment of ₱{amount} for Invoice {invoice.invoice_no} via {method.title()}"
        )
        
        messages.success(request, f"Successfully received ₱{amount} for {invoice.invoice_no}.")
        return redirect('billing_payment:customer_ledger', pk=invoice.customer.id)
        
    return redirect('billing_payment:customer_list')

def sales_list(request):
    all_transactions = Transaction.objects.all().order_by('-date_completed')
    
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    method_filter = request.GET.get('method', '')

    if search_query:
        all_transactions = all_transactions.filter(
            Q(transaction_ref__icontains=search_query) |
            Q(customer__name__icontains=search_query) | 
            Q(processed_by__username__icontains=search_query)
        )

    if status_filter:
        all_transactions = all_transactions.filter(status__iexact=status_filter)

    if method_filter:
        all_transactions = all_transactions.filter(payment_method__iexact=method_filter)

    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(all_transactions, per_page) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'transactions': page_obj,
        'per_page': per_page, 
        'search_query': search_query, 
        'status_filter': status_filter, 
        'method_filter': method_filter, 
    }
    return render(request, 'billing_payment/sales_list.html', context)

def transaction_details(request, txn_id):
    transaction = get_object_or_404(Transaction, id=txn_id)
    items = transaction.sold_items.all()
    
    context = {
        'transaction': transaction,
        'items': items
    }
    return render(request, 'billing_payment/transaction_details.html', context)

def get_sale_details_api(request, txn_id):
    try:
        transaction = Transaction.objects.get(id=txn_id)
        items = transaction.sold_items.all() 
        
        items_data = []
        for item in items:
            # Safe calculation: Subtotal divided by Quantity
            # If quantity is 0 (to avoid division by zero error), set to 0
            computed_price = float(item.subtotal) / int(item.quantity) if int(item.quantity) > 0 else 0
            
            items_data.append({
                'name': item.inventory_item.item_name,
                'price': computed_price,
                'qty': item.quantity,
                'subtotal': float(item.subtotal)
            })
             
        return JsonResponse({
            'status': 'success',
            'ref': transaction.transaction_ref or transaction.id,
            'total_amount': float(transaction.total_amount),
            'items': items_data
        })
    except Transaction.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Transaction not found'})
    except Exception as e:
        # Catch any other backend errors so it doesn't cause a Network Error in JS
        return JsonResponse({'status': 'error', 'message': str(e)})
    
def invoice_list_view(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    per_page = request.GET.get('per_page', 10)

    invoices = Invoice.objects.exclude(customer__isnull=True).prefetch_related('items').order_by('-issue_date', '-id')

    if search_query:
        invoices = invoices.filter(
            Q(invoice_no__icontains=search_query) | 
            Q(customer__name__icontains=search_query)
        )

    if status_filter:
        invoices = invoices.filter(status__iexact=status_filter)

    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(invoices, per_page)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)

    today = timezone.now().date()

    context = {
        'invoices': invoices_page, 
        'today': today,
        'search_query': search_query,
        'status_filter': status_filter,
        'per_page': per_page,  
    }
    
    return render(request, 'billing_payment/invoice_list.html', context)

def create_invoice_view(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)
        
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                invoice = form.save(commit=False)
                invoice.save() 
                
                formset.instance = invoice
                invoice_items = formset.save()
                
                grand_total = sum(item.subtotal for item in invoice.items.all())
                
                invoice.total_amount = grand_total
                invoice.balance_due = grand_total 
                invoice.save()
                
            log_system_activity(
                    user=request.user,
                    action="CREATE INVOICE",
                    description=f"Manually created invoice {invoice.invoice_no} (Total: ₱{grand_total})"
                )
                
            return redirect('billing_payment:invoice_list')
    else:
        form = InvoiceForm()
        formset = InvoiceItemFormSet()
        
    context = {
        'form': form,
        'formset': formset
    }
    return render(request, 'billing_payment/create_invoice.html', context)

def invoice_items_json(request, invoice_id):
    invoice = get_object_or_404(Invoice, id=invoice_id)
    items = invoice.items.all() 
    
    data = {
        'items': [
            {
                'product_name': item.product_name,
                'quantity': item.quantity,
                'unit_price': str(item.unit_price),
                'subtotal': str(item.subtotal),
            } for item in items
        ]
    }
    return JsonResponse(data)

def sales_return_list(request):
    query = request.GET.get('q', '').strip()
    
    returns = SalesReturn.objects.select_related(
        'transaction', 
        'transaction__customer', 
        'transaction__processed_by'
    ).all().order_by('-created_at')
    
    if query:
        returns = returns.filter(
            Q(return_id__icontains=query) |
            Q(transaction__transaction_ref__icontains=query) |
            Q(transaction__customer__name__icontains=query) | 
            Q(transaction__processed_by__username__icontains=query) 
        )
    
    total_refunds = returns.aggregate(Sum('total_refund'))['total_refund__sum'] or 0
    return_count = returns.count()
    
    returns_per_page = request.GET.get('returns_per_page', 10)
    try:
        returns_per_page = int(returns_per_page)
    except ValueError:
        returns_per_page = 10

    page_number = request.GET.get('page', 1)
    paginator = Paginator(returns, returns_per_page, orphans=0)
    returns_page = paginator.get_page(page_number)
    
    context = {
        'returns': returns_page,
        'total_refunds': total_refunds,
        'return_count': return_count,
        'query': query,
        'returns_per_page': returns_per_page, 
    }
    return render(request, 'billing_payment/sales_return_list.html', context)

def process_return(request):
    if request.method == 'POST':
        txn_ref = request.POST.get('transaction_ref')
        product_ids = request.POST.getlist('product_id[]')
        return_qtys = request.POST.getlist('return_qty[]')
        reasons = request.POST.getlist('reason[]')

        txn = get_object_or_404(Transaction, transaction_ref=txn_ref)
        return_id = f"RET-{uuid.uuid4().hex[:6].upper()}"

        sales_return = SalesReturn.objects.create(
            transaction=txn,
            return_id=return_id,
            reason=reasons[0] if reasons else "Multiple Items",
            total_refund=0 
        )

        running_total = 0 

        for i, prod_id in enumerate(product_ids):
            qty = int(return_qtys[i])
            if qty > 0:
                product = InventoryItem.objects.get(id=prod_id)
                item_in_txn = txn.sold_items.get(inventory_item=product)
                
                line_total = item_in_txn.unit_price * qty
                running_total += line_total 

                SalesReturnItem.objects.create(
                    sales_return=sales_return,
                    product=product,
                    quantity=qty,
                    subtotal=line_total
                )

                product.quantity += qty
                product.save()

        sales_return.total_refund = running_total
        sales_return.save()

        log_system_activity(
            user=request.user,
            action="SALES RETURN",
            description=f"Processed return {return_id} for Transaction {txn_ref}. Refund: ₱{running_total}"
        )
        
        messages.success(request, f"Return {return_id} processed! Refund Amount: ₱{running_total}")
        return redirect('billing_payment:sales_return_list')

def verify_transaction(request):
    txn_ref = request.GET.get('txn_ref')
    try:
        txn = Transaction.objects.get(transaction_ref=txn_ref)
        items_data = []

        for sold_item in txn.sold_items.all():
            
            returned_qty = SalesReturnItem.objects.filter(
                sales_return__transaction=txn,
                product=sold_item.inventory_item
            ).aggregate(Sum('quantity'))['quantity__sum'] or 0

            remaining_qty = sold_item.quantity - returned_qty

            if remaining_qty > 0:
                items_data.append({
                    'id': sold_item.inventory_item.id,
                    'name': sold_item.inventory_item.item_name, # Note: Binago ko ito papuntang .item_name baka ito ang ginagamit mo sa model
                    'max_qty': remaining_qty 
                })

        if items_data:
            return JsonResponse({'success': True, 'items': items_data})
        else:
            return JsonResponse({'success': False, 'message': 'All items from this transaction have already been returned.'})

    except Transaction.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Transaction not found.'})