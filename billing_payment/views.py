from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Customer, Invoice, InvoicePayment # <--- Make sure InvoicePayment is imported
from decimal import Decimal
from point_of_sale.models import Transaction
from django.http import JsonResponse
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