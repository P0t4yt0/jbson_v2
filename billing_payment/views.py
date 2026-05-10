from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Customer, Invoice, InvoicePayment 
from .forms import InvoiceForm, InvoiceItemFormSet
from decimal import Decimal
from point_of_sale.models import Transaction
from django.http import JsonResponse
from django.utils import timezone  
from django.db import models

def customer_list(request):
    # Handle Adding a New Customer
    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        limit = request.POST.get('credit_limit')
        terms = request.POST.get('payment_terms')
        
        # Basic validation to prevent duplicates
        if Customer.objects.filter(name=name).exists():
            messages.error(request, f"A customer named {name} already exists.")
        else:
            Customer.objects.create(
                name=name,
                phone=phone,
                is_credit_customer=True, # Default to True since we are adding them here
                credit_limit=limit,
                payment_terms=terms,
                credit_status='active'
            )
            messages.success(request, f"Customer '{name}' added successfully.")
        return redirect('billing_payment:customer_list')

    # Fetch all customers for the table
    customers = Customer.objects.all().order_by('-credit_balance')
    
    return render(request, 'billing_payment/customer_list.html', {
        'customers': customers
    })

def customer_ledger(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    
    # Get all invoices for this customer, newest first
    invoices = customer.invoices.all().order_by('-issue_date', '-id')
    
    return render(request, 'billing_payment/customer_ledger.html', {
        'customer': customer,
        'invoices': invoices
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
        # (Remember: Your InvoicePayment model automatically deducts the balances in its save() method)
        InvoicePayment.objects.create(
            invoice=invoice,
            amount=amount,
            method=method,
            processed_by=request.user if request.user.is_authenticated else None
        )
        
        messages.success(request, f"Successfully received ₱{amount} for {invoice.invoice_no}.")
        return redirect('billing_payment:customer_ledger', pk=invoice.customer.id)
        
    return redirect('billing_payment:customer_list')

def sales_list(request):
    # Kukunin natin yung mga successful transactions mula sa POS
    transactions = Transaction.objects.filter(
        status__in=['completed', 'credit']
    ).select_related('customer', 'processed_by').order_by('-date_completed')
    
    context = {
        'transactions': transactions
    }
    return render(request, 'billing_payment/sales_list.html', context)

def transaction_details(request, txn_id):
    # Hanapin ang transaction gamit ang ID
    transaction = get_object_or_404(Transaction, id=txn_id)
    
    # Kunin lahat ng items na binili sa transaction na ito
    items = transaction.sold_items.all()
    
    context = {
        'transaction': transaction,
        'items': items
    }
    return render(request, 'billing_payment/transaction_details.html', context)

def get_sale_details_api(request, txn_id):
    try:
        transaction = Transaction.objects.get(id=txn_id)
        # Kukunin natin ang mga items sa loob ng transaction
        items = transaction.sold_items.all() 
        
        items_data = []
        for item in items:
            items_data.append({
                'name': item.inventory_item.item_name,
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
    
def invoice_list_view(request):
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')

    invoices = Invoice.objects.exclude(customer__isnull=True).prefetch_related('items')

    if search_query:
        invoices = invoices.filter(
            models.Q(invoice_no__icontains=search_query) | 
            models.Q(customer__name__icontains=search_query)
        )

    if status_filter:
        invoices = invoices.filter(status__iexact=status_filter)

    invoices = invoices.order_by('-issue_date')

    today = timezone.now().date()

    return render(request, 'billing_payment/invoice_list.html', {
        'invoices': invoices,
        'today': today,
        'search_query': search_query,
        'status_filter': status_filter
    })

def create_invoice_view(request):
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        formset = InvoiceItemFormSet(request.POST)
        
        # Siguraduhing valid ang parehong forms bago mag-save
        if form.is_valid() and formset.is_valid():
            
            # Gagamit tayo ng atomic transaction para siguradong saved lahat o none at all
            with transaction.atomic():
                # 1. I-save muna ang main Invoice pero wag muna i-commit sa DB
                invoice = form.save(commit=False)
                invoice.save() # Kailangan nating i-save muna para magkaroon ng ID para sa formset
                
                # 2. Ikonekta ang formset sa main invoice at i-save ang items
                formset.instance = invoice
                invoice_items = formset.save()
                
                # 3. AUTOMATIC COMPUTATION: I-plus lahat ng subtotals para makuha ang grand total
                grand_total = sum(item.subtotal for item in invoice.items.all())
                
                # I-update ang main invoice
                invoice.total_amount = grand_total
                invoice.balance_due = grand_total # Kung unpaid, balance = total
                invoice.save()
                
            return redirect('billing_payment:invoice_list') # Balik sa listahan
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
    # Tandaan: 'items' ang related_name natin sa models
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