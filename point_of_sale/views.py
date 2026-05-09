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
        return HttpResponse("No active transaction.")

    transaction = get_object_or_404(Transaction, id=transaction_id, status='open')

    method = request.GET.get('method', 'Cash')
    received = Decimal(request.GET.get('received', '0'))
    ref_num = request.GET.get('ref_num', '').strip()
    customer_id = request.GET.get('customer_id')

    try:
        with db_transaction.atomic():

            # STOCK DEDUCTION
            for item in transaction.sold_items.all():
                product = item.inventory_item
                if product.quantity < item.quantity:
                    return HttpResponse(f"Insufficient stock for {product.item_name}")
                product.quantity -= item.quantity
                product.save()

            # ===== TRADE CREDIT =====
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

                Invoice.objects.create(
                    transaction=transaction,
                    customer=customer,
                    total_amount=transaction.total_amount,
                    balance_due=transaction.total_amount
                )

                customer.credit_balance += transaction.total_amount
                customer.save()

            # ===== CASH / ONLINE BANK =====
            else:
                if method == 'Online Wallet' and not ref_num:
                    return HttpResponse("Reference number required.")

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

            del request.session['transaction_id']

        return render(request, 'point_of_sale/receipts/thermal_print.html', {
            'transaction': transaction,
            'sold_items': transaction.sold_items.all(),
            'amount_received': received,
            
            'change': received - transaction.total_amount, 
            
            'ref_num': ref_num
        })

    except Exception as e:
        return HttpResponse(str(e))
    
    
def void_transaction(request):
    Transaction.objects.filter(
        status='open',
        processed_by=request.user if request.user.is_authenticated else None
    ).update(status='voided')
    return redirect('point_of_sale:pos_index')


def reset_transaction(request):
    return void_transaction(request)

def quotation_list_view(request):
    """Kukunin lang natin yung mga transactions na may status na 'quotation'"""
    # Kukunin lahat ng naka-draft pa lang
    quotations = Transaction.objects.filter(status='quotation').order_by('-date_created')
    
    context = {
        'quotations': quotations
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