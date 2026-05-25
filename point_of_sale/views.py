import json

# 1. Django Shortcuts
from django.shortcuts import render, redirect, get_object_or_404

# 2. HTTP Responses
from django.http import JsonResponse, HttpResponse

# 3. Database Transactions
from django.db import transaction as db_transaction

# 4. POS Models
from .models import Transaction, TransactionItem

# 5. Inventory Models
from inventory.models import InventoryItem, Category

# 6. Billing / Credit Models
from billing_payment.models import Customer, Invoice, Payment


from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from decimal import Decimal
from activity_log.utils import log_system_activity
from billing_payment.models import Invoice, InvoiceItem
from django.db.models import Q, F, ProtectedError, Sum, DecimalField
from django.core.paginator import Paginator
from notifications.models import Notification


def pos_view(request):
    products = InventoryItem.objects.all()
    categories = Category.objects.all()
    credit_customers = Customer.objects.filter(is_credit_customer=True, credit_status='active')

    transaction_id = request.session.get('transaction_id')
    transaction = None

    if transaction_id:
        transaction = Transaction.objects.filter(id=transaction_id, status='open').first()

    if not transaction:
        transaction = Transaction.objects.create(
            status='open',
            processed_by=request.user if request.user.is_authenticated else None
        )
        request.session['transaction_id'] = transaction.id

    sold_items = transaction.sold_items.all()

    return render(request, 'point_of_sale/pos.html', {
        'products': products,
        'categories': categories,
        'credit_customers': credit_customers,
        'transaction': transaction,
        'sold_items': sold_items,
    })

def add_to_cart(request):
    product = get_object_or_404(InventoryItem, id=request.GET.get('product_id'))

    transaction_id = request.session.get('transaction_id')
    transaction, _ = Transaction.objects.get_or_create(
        id=transaction_id,
        status='open',
        defaults={'processed_by': request.user}
    )
    request.session['transaction_id'] = transaction.id

    cart_item, created = TransactionItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'quantity': 1,
            'subtotal': product.price
        }
    )

    if not created:
        cart_item.quantity += 1
        cart_item.subtotal = cart_item.quantity * cart_item.unit_price
        cart_item.save()

    transaction.calculate_totals()
    return JsonResponse({'status': 'success'})

@csrf_exempt
def update_cart_item(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            item_id = data.get('item_id')
            action = data.get('action')
            new_qty = data.get('quantity') # Idagdag ito para makuha ang tinype na number
            
            try:
                cart_item = TransactionItem.objects.get(id=item_id)
            except TransactionItem.DoesNotExist:
                return JsonResponse({'status': 'success'})
                
            transaction = cart_item.transaction
            
            # 1. Update Quantity
            if action == 'increase':
                cart_item.quantity += 1
            elif action == 'decrease':
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                else:
                    action = 'remove'
            # ─── BAGONG LOGIC PARA SA TYPABLE INPUT ───
            elif action == 'set':
                try:
                    qty_val = int(new_qty)
                    if qty_val > 0:
                        cart_item.quantity = qty_val
                    else:
                        action = 'remove' # Kapag nag-type ng 0 o negative, buburahin ang item
                except (ValueError, TypeError):
                    pass # Kapag invalid ang tinype, i-ignore lang
            # ──────────────────────────────────────────
            
            # 2. Save Item or Delete
            if action == 'remove':
                cart_item.delete()
            else:
                cart_item.subtotal = cart_item.quantity * cart_item.unit_price
                cart_item.save()
            
            # ─── 3. BULLETPROOF TOTAL RECALCULATION ───
            # Kukunin nito lahat ng items na kapareho ng transaction ID
            remaining_items = TransactionItem.objects.filter(transaction=transaction)
            
            new_total = 0
            for item in remaining_items:
                new_total += item.subtotal
                
            transaction.total_amount = new_total
            transaction.save()
            # ──────────────────────────────────────────
            
            return JsonResponse({'status': 'success'})
            
        except Exception as e:
            # I-print sa terminal para makita natin ang totoong error
            print(f"POS UPDATE ERROR: {str(e)}") 
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        

def add_by_barcode(request):
    barcode = request.GET.get('barcode')
    product = InventoryItem.objects.filter(barcode_id=barcode).first()

    if not product:
        return JsonResponse({'status': 'error', 'message': 'Product not found'})

    transaction = Transaction.objects.filter(
        status='open',
        processed_by=request.user if request.user.is_authenticated else None
    ).first()

    if not transaction:
        transaction = Transaction.objects.create(
            status='open',
            processed_by=request.user if request.user.is_authenticated else None
        )
        request.session['transaction_id'] = transaction.id

    item, created = TransactionItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'quantity': 1,
            'subtotal': product.price
        }
    )

    if not created:
        item.quantity += 1
        item.subtotal = item.quantity * item.unit_price
        item.save()

    transaction.calculate_totals()
    return JsonResponse({'status': 'success'})

    
def process_payment(request):
    transaction_id = request.session.get('transaction_id')
    if not transaction_id:
        messages.error(request, "No active transaction found.")
        return redirect('point_of_sale:pos_index')

    transaction = get_object_or_404(Transaction, id=transaction_id, status='open')

    method = request.GET.get('method', 'Cash')
    received = Decimal(request.GET.get('received', '0'))
    ref_num = request.GET.get('ref_num', '').strip()
    customer_id = request.GET.get('customer_id')

    try:
        with db_transaction.atomic():
            
            # --- FIX 1: PRE-CHECK STOCKS BAGO BUMAWAS ---
            # I-check muna lahat kung sapat ang stock bago galawin ang database
            for item in transaction.sold_items.all():
                if item.inventory_item.quantity < item.quantity:
                    messages.error(request, f"Insufficient stock for {item.inventory_item.item_name}. Only {item.inventory_item.quantity} left.")
                    return redirect('point_of_sale:pos_index')

            # --- 1. STOCK DEDUCTION (Gagalaw lang kapag safe na lahat) ---
            for item in transaction.sold_items.all():
                product = item.inventory_item
                
                # Deduct the stock
                product.quantity -= item.quantity
                product.save()

                # --- THE NOTIFICATION TRIGGER ---
                if product.quantity <= 10: 
                    alert_exists = Notification.objects.filter(
                        notification_type='low_stock',
                        source_id=str(product.id),
                        is_read=False
                    ).exists()

                    if not alert_exists:
                        Notification.objects.create(
                            notification_type='low_stock',
                            priority='critical', 
                            title=f"Low Stock: {product.item_name}",
                            message=f"Stock dropped to {product.quantity} after a POS transaction. Please reorder.",
                            source_table='inventory',
                            source_id=str(product.id),
                            action_url='/inventory/purchase-orders/create/?auto=true' 
                       )

            invoice = None

            # ===== 2. TRADE CREDIT LOGIC =====
            if method == 'Trade Credit':
                if not customer_id:
                    messages.error(request, "Select a customer for Trade Credit.")
                    return redirect('point_of_sale:pos_index')

                customer = get_object_or_404(Customer, id=customer_id)

                if not customer.is_credit_customer:
                    messages.error(request, "Customer not approved for Trade Credit.")
                    return redirect('point_of_sale:pos_index')

                if customer.check_overdue_status() or customer.credit_status == 'hold':
                    messages.error(request, "Customer account is on HOLD.")
                    return redirect('point_of_sale:pos_index')

                if customer.credit_balance + transaction.total_amount > customer.credit_limit:
                    messages.error(request, "Credit limit exceeded.")
                    return redirect('point_of_sale:pos_index')

                transaction.payment_method = 'credit'
                transaction.customer = customer
                transaction.status = 'credit'
                transaction.date_completed = timezone.now()
                transaction.save()

                invoice = Invoice.objects.create(
                    transaction=transaction,
                    customer=customer,
                    total_amount=transaction.total_amount,
                    balance_due=transaction.total_amount,
                    status='unpaid' 
                )

                customer.credit_balance += transaction.total_amount
                customer.save()

            # ===== 3. CASH / ONLINE BANK LOGIC =====
            else:
                # --- FIX 2: ALISIN ANG HTTP RESPONSE DITO ---
                if method == 'Online Wallet' and not ref_num:
                    messages.error(request, "Reference number required for Online Bank/Wallet.")
                    return redirect('point_of_sale:pos_index')

                transaction.payment_method = 'cash' if method == 'Cash' else 'bank'
                transaction.status = 'completed'
                transaction.amount_received = received
                transaction.reference_number = ref_num
                transaction.date_completed = timezone.now()
                transaction.save()

                Payment.objects.create(
                    transaction=transaction,
                    payment_method=transaction.payment_method,
                    amount_due=transaction.total_amount,
                    amount_tendered=received,
                    status='success'
                )

                customer_obj = None
                if customer_id and customer_id != 'None' and customer_id != '':
                    customer_obj = Customer.objects.filter(id=customer_id).first()

                invoice = Invoice.objects.create(
                    transaction=transaction,
                    customer=customer_obj, 
                    total_amount=transaction.total_amount,
                    balance_due=0, 
                    status='paid'
                )

            # ===== 4. DYNAMIC INVOICE ITEMS CLONING =====
            if invoice:
                for item in transaction.sold_items.all():
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product_name=item.inventory_item.item_name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        subtotal=item.subtotal
                    )

            payment_type = "Trade Credit" if method == 'Trade Credit' else method
            
            log_system_activity(
                user=request.user,
                action="POS TRANSACTION",
                description=f"Processed POS transaction {transaction.transaction_ref} via {payment_type} (Total: ₱{transaction.total_amount})"
            )
            # --------------------------------

            del request.session['transaction_id']

        return render(request, 'point_of_sale/receipts/thermal_print.html', {
            'transaction': transaction,
            'sold_items': transaction.sold_items.all(),
            'amount_received': received,
            'change': received - transaction.total_amount, 
            'ref_num': ref_num
        })

    except Exception as e:
        import traceback          # <-- ADD THIS
        traceback.print_exc()     # <-- ADD THIS: It will print the exact crashing line in your VSCode Terminal!
        # --- FIX 3: SWEETALERT INSTEAD OF WHITE SCREEN ON ANY ERROR ---
        messages.error(request, f"Transaction Error: {str(e)}")
        return redirect('point_of_sale:pos_index')
    
    
def void_transaction(request):
    # 1. Kunin ang current transaction ID mula sa session
    transaction_id = request.session.get('transaction_id')
    
    if transaction_id:
        try:
            # 2. Hanapin ang active transaction gamit ang ID
            transaction = Transaction.objects.get(id=transaction_id, status='open')
            
            # 3. Burahin ang transaction (automatic mabubura rin ang cart items nito kung naka-CASCADE)
            transaction.delete()
            
            # 4. Tanggalin ang transaction_id sa session para ma-reset ang cart
            del request.session['transaction_id']
            
            # Mag-trigger ng success message
            messages.success(request, "Order has been successfully voided.")
        except Transaction.DoesNotExist:
            # Fallback kung hindi nahanap sa database
            if 'transaction_id' in request.session:
                del request.session['transaction_id']
            messages.error(request, "Transaction already voided or does not exist.")
    else:

        open_transactions = Transaction.objects.filter(status='open')
        if open_transactions.exists():
            open_transactions.delete()
            messages.success(request, "All open transactions have been cleared.")
        else:
            messages.info(request, "Cart is already empty.")

    return redirect('point_of_sale:pos_index')


def reset_transaction(request):
    return void_transaction(request)

def quotation_list_view(request):
    # 1. Kunin ang mga parameters
    search_query = request.GET.get('search', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    per_page = request.GET.get('per_page', 10)

    # 2. Base query
    quotations = Transaction.objects.filter(status='quotation').order_by('-date_created')

    # 3. Apply Search Filter
    if search_query:
        quotations = quotations.filter(
            Q(transaction_ref__icontains=search_query)
        )

    # 4. Apply Date Filters
    if start_date:
        # __date__gte ay ginagamit para i-compare ang exact date sa DateTimeField
        quotations = quotations.filter(date_created__date__gte=start_date)
    
    if end_date:
        quotations = quotations.filter(date_created__date__lte=end_date)

    # 5. Pagination
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(quotations, per_page)
    page_number = request.GET.get('page', 1)
    quotations_page = paginator.get_page(page_number)

    # 6. Ipasa pabalik sa context
    context = {
        'quotations': quotations_page,
        'search_query': search_query,
        'start_date': start_date,  # <-- Important para hindi mawala yung laman ng box
        'end_date': end_date,      # <-- Important para hindi mawala yung laman ng box
        'per_page': per_page,
    }
    
    return render(request, 'point_of_sale/quotation_list.html', context)

def save_as_quotation(request, transaction_id):
    """Ise-save ang current open transaction bilang draft/quotation"""
    # Hanapin yung open transaction
    transaction = get_object_or_404(Transaction, id=transaction_id, status='open')
    
    # I-check kung may laman ba yung cart bago i-save as quotation
    if not transaction.sold_items.exists():
        messages.error(request, "No items in cart! Unable to save as quotation.")
        return redirect('pos:pos_index') # Palitan ng tamang pangalan ng main POS view niyo

    # Kung may laman, palitan ang status!
    transaction.status = 'quotation'
    transaction.save()

    log_system_activity(
        user=request.user,
        action="SAVE QUOTATION",
        description=f"Saved open transaction as Quotation Ref: {transaction.transaction_ref}"
    )

    messages.success(request, f"Quotation {transaction.transaction_ref} saved successfully!")
    
    # I-redirect pabalik sa POS screen para makapag-transact ng bago
    return redirect('pos:pos_index')

def load_quotation_to_pos(request, transaction_id):
    """Kukunin ang quotation at ilo-load pabalik sa mismong POS screen"""
    # 1. Hanapin yung quotation gamit ang ID
    transaction = get_object_or_404(Transaction, id=transaction_id, status='quotation')
    
    # 2. Ibalik ang status niya sa 'open' para maging active na cart ulit siya
    transaction.status = 'open'
    transaction.save()

    log_system_activity(
        user=request.user,
        action="LOAD QUOTATION",
        description=f"Loaded Quotation Ref: {transaction.transaction_ref} into POS cart"
    )
    
    # 3. I-set sa session yung ID para pag-load ng POS view, ito yung bubuksan niya
    request.session['transaction_id'] = transaction.id
    
    messages.success(request, f"Quotation {transaction.transaction_ref} loaded to POS!")
    
    # 4. I-redirect pabalik sa main POS screen
    return redirect('pos:pos_index')

def get_quotation_details(request):
    ref_number = request.GET.get('ref')
    
    try:
        transaction = Transaction.objects.get(transaction_ref=ref_number)
        
        # DITO TAYO MAGPAPALIT: Ginamit natin ang TransactionItem
        items = TransactionItem.objects.filter(transaction=transaction)
        
        items_data = []
        for item in items:
            items_data.append({
                # Note: I-check mo rin kung 'inventory_item' ba talaga ang field name
                # ng product sa loob ng TransactionItem model mo. Kung iba, palitan mo rin ito.
                'name': item.inventory_item.item_name,
                'qty': item.quantity,
                'subtotal': float(item.subtotal) 
            })
            
        return JsonResponse({
            'status': 'success',
            'total_amount': float(transaction.total_amount),
            'items': items_data
        })
    except Transaction.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Quotation not found'})
    
def reprint_receipt(request, txn_id):
    transaction = get_object_or_404(Transaction, id=txn_id)
    
    # Kukunin natin yung nai-save na amount_received kung meron. 
    # Kung walang 'amount_received' field sa model mo, ifa-fallback natin sa total_amount.
    received = getattr(transaction, 'amount_received', transaction.total_amount)
    ref_num = getattr(transaction, 'reference_number', '')

    context = {
        'transaction': transaction,
        'sold_items': transaction.sold_items.all(),
        'amount_received': received,
        'change': received - transaction.total_amount,
        'ref_num': ref_num
    }
    return render(request, 'point_of_sale/receipts/thermal_print.html', context)