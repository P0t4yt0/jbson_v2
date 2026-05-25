from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Customer, Invoice, InvoicePayment
from decimal import Decimal
from point_of_sale.models import Transaction
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Q
from .models import SalesReturn, SalesReturnItem
import uuid
from inventory.models import InventoryItem
from activity_log.utils import log_system_activity
from django.core.paginator import Paginator
from django.db import transaction

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
            log_system_activity(
                user=request.user,
                action="NEW CUSTOMER",
                description=f"Added new credit customer: '{name}'"
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
        log_system_activity(
            user=request.user,
            action="PAYMENT RECEIVED",
            description=f"Received payment of ₱{amount} for Invoice {invoice.invoice_no} via {method.title()}"
        )
        
        messages.success(request, f"Successfully received ₱{amount} for {invoice.invoice_no}.")
        return redirect('billing_payment:customer_ledger', pk=invoice.customer.id)
        
    return redirect('billing_payment:customer_list')

def sales_list(request):
    # 1. Kunin muna lahat ng transactions, pababa (latest first)
    all_transactions = Transaction.objects.all().order_by('-date_completed')
    
    # --- KUNIN ANG MGA FILTERS MULA SA URL ---
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    method_filter = request.GET.get('method', '')

    # --- I-APPLY ANG MGA FILTERS KUNG MERON ---
    
    # A. Search Filter (Reference No, Customer Name, or Cashier)
    if search_query:
        all_transactions = all_transactions.filter(
            Q(transaction_ref__icontains=search_query) |
            Q(customer__name__icontains=search_query) | 
            Q(processed_by__username__icontains=search_query)
        )

    # B. Status Filter
    if status_filter:
        all_transactions = all_transactions.filter(status__iexact=status_filter)

    # C. Method Filter
    if method_filter:
        all_transactions = all_transactions.filter(payment_method__iexact=method_filter)

    # --- PAGINATION LOGIC ---
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(all_transactions, per_page) 
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # --- IPASA SA CONTEXT ---
    context = {
        'transactions': page_obj,
        'per_page': per_page, 
        'search_query': search_query,   # Para hindi mawala ang tinype sa search box
        'status_filter': status_filter, # Para manatiling selected ang piniling status
        'method_filter': method_filter, # Para manatiling selected ang piniling method
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
    # 1. Kunin ang mga parameters galing sa URL
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '')
    per_page = request.GET.get('per_page', 10)

    # 2. Base query: Kunin lahat ng invoices (ordered by latest)
    invoices = Invoice.objects.exclude(customer__isnull=True).prefetch_related('items').order_by('-issue_date', '-id')

    # 3. I-apply ang Search Filter (Hahanapin ang Invoice No. o Customer Name)
    if search_query:
        invoices = invoices.filter(
            Q(invoice_no__icontains=search_query) | 
            Q(customer__name__icontains=search_query)
        )

    # 4. I-apply ang Status Filter
    if status_filter:
        invoices = invoices.filter(status__iexact=status_filter)

    # 5. Setup ang Pagination para gumana yung sa HTML natin
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(invoices, per_page)
    page_number = request.GET.get('page', 1)
    invoices_page = paginator.get_page(page_number)

    today = timezone.now().date()

    # 6. Ipasa sa context
    context = {
        'invoices': invoices_page,  # Ito na yung paginated na data
        'today': today,
        'search_query': search_query,
        'status_filter': status_filter,
        'per_page': per_page,       # Para hindi bumalik sa 10 ang dropdown
    }
    
    return render(request, 'billing_payment/invoice_list.html', context)

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

def sales_return_list(request):
    query = request.GET.get('q', '').strip()
    
    # Gumamit ng select_related para mas mabilis kunin ang data ng transaction, customer, at cashier
    returns = SalesReturn.objects.select_related(
        'transaction', 
        'transaction__customer', 
        'transaction__processed_by'
    ).all().order_by('-created_at')
    
    # --- SEARCH FILTER LOGIC ---
    if query:
        returns = returns.filter(
            Q(return_id__icontains=query) |
            Q(transaction__transaction_ref__icontains=query) |
            Q(transaction__customer__name__icontains=query) |           # Hinahanap ang Customer Name
            Q(transaction__processed_by__username__icontains=query)     # Hinahanap ang Cashier Username
        )
    
    # --- SUMMARY DATA ---
    total_refunds = returns.aggregate(Sum('total_refund'))['total_refund__sum'] or 0
    return_count = returns.count()
    
    # --- DYNAMIC PAGINATION LOGIC ---
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

        # 1. Gawa muna ng base record
        sales_return = SalesReturn.objects.create(
            transaction=txn,
            return_id=return_id,
            reason=reasons[0] if reasons else "Multiple Items",
            total_refund=0 # Temporary zero
        )

        running_total = 0 # Dito natin ipon-ipunin ang presyo

        for i, prod_id in enumerate(product_ids):
            qty = int(return_qtys[i])
            if qty > 0:
                product = InventoryItem.objects.get(id=prod_id)
                # Kunin ang unit price mula sa TransactionItem (hindi sa Inventory para accurate sa receipt)
                item_in_txn = txn.sold_items.get(inventory_item=product)
                
                line_total = item_in_txn.unit_price * qty
                running_total += line_total # I-add sa grand total

                SalesReturnItem.objects.create(
                    sales_return=sales_return,
                    product=product,
                    quantity=qty,
                    subtotal=line_total
                )

                # Update Inventory Stock
                product.quantity += qty
                product.save()

        # 2. KRITIKAL: I-save ang final total sa database!
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

        # Iikot sa lahat ng biniling items sa transaction na ito
        for sold_item in txn.sold_items.all():
            
            # I-compute kung ilan na ang naibalik dati sa partikular na item na ito
            returned_qty = SalesReturnItem.objects.filter(
                sales_return__transaction=txn,
                product=sold_item.inventory_item
            ).aggregate(Sum('quantity'))['quantity__sum'] or 0

            # Ibawas ang naibalik na sa orihinal na binili
            remaining_qty = sold_item.quantity - returned_qty

            # Kung may natitira pa, isama sa listahan ng pwedeng i-return
            if remaining_qty > 0:
                items_data.append({
                    'id': sold_item.inventory_item.id,
                    'name': sold_item.inventory_item.name,
                    'max_qty': remaining_qty  # Ito na ang updated na pwede i-return
                })

        # Kung may laman pa ang items_data, ibig sabihin may pwede pang i-return
        if items_data:
            return JsonResponse({'success': True, 'items': items_data})
        else:
            return JsonResponse({'success': False, 'message': 'All items from this transaction have already been returned.'})

    except Transaction.DoesNotExist:
        return JsonResponse({'success': False, 'message': 'Transaction not found.'})
    