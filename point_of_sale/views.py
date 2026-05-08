# 1. Django Shortcuts (Rendering and Redirecting)
from django.shortcuts import render, redirect, get_object_or_404

# 2. HTTP Responses (For AJAX/JavaScript calls)
from django.http import JsonResponse, HttpResponse

# 3. Database Tools (For safe stock deduction)
from django.db import transaction as db_transaction

# 4. Your App's Models (POS models)
from .models import Transaction, TransactionItem, CartItem

# 5. External App Models (Inventory models)
from inventory.models import InventoryItem, Category

from django.utils import timezone

def pos_view(request):
    # 1. Kunin ang products at categories para sa sidebar/grid
    products = InventoryItem.objects.all()
    categories = Category.objects.all() 
    
    # 2. Check muna natin sa session kung may existing order na itong browser na ito
    transaction_id = request.session.get('transaction_id')
    transaction = None

    if transaction_id:
        try:
            # Hanapin ang specific transaction na nasa session na 'open' pa
            transaction = Transaction.objects.get(id=transaction_id, status='open')
        except Transaction.DoesNotExist:
            # Kung wala o tapos na, i-reset ang variable para gumawa ng bago
            transaction = None

    # 3. Kung walang nahanap sa session, gumawa ng brand new transaction
    if not transaction:
        transaction = Transaction.objects.create(
            status='open',
            processed_by=request.user if request.user.is_authenticated else None
        )
        # I-save ang bagong ID sa session para ito ang gamitin sa susunod na refresh
        request.session['transaction_id'] = transaction.id

    # 4. Kunin ang items gamit ang bagong related_name na 'cart_items'
    cart_items = transaction.cart_items.all()

    context = {
        'products': products,
        'categories': categories,
        'transaction': transaction,
        'cart_items': cart_items,
    }
    
    return render(request, 'point_of_sale/pos.html', context)

def add_to_cart(request):
    product_id = request.GET.get('product_id')
    product = get_object_or_404(InventoryItem, id=product_id)
    
    # 1. Kunin or gawa ng transaction
    transaction_id = request.session.get('transaction_id')
    transaction, created = Transaction.objects.get_or_create(
        id=transaction_id, 
        status='open', 
        defaults={'processed_by': request.user}
    )
    
    # Siguraduhing naka-save sa session yung ID
    request.session['transaction_id'] = transaction.id

    # 2. Check kung nandun na yung item sa cart
    # GAMITIN ANG 'cart_items' dito (hindi 'items')
    cart_item, created = CartItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'subtotal': product.price,
            'quantity': 1
        }
    )

    if not created:
        cart_item.quantity += 1
        cart_item.subtotal = cart_item.unit_price * cart_item.quantity
        cart_item.save()

    # 3. I-update ang grand total ng transaction
    transaction.calculate_totals()

    return JsonResponse({'status': 'success'})

def process_payment(request):
    # 1. Kunin ang transaction_id mula sa session
    transaction_id = request.session.get('transaction_id')
    
    if not transaction_id:
        # Fallback: Hanapin ang huling 'open' na transaction
        latest_pending = Transaction.objects.filter(status='open').order_by('-date_created').first()
        if latest_pending:
            transaction_id = latest_pending.id
        else:
            return HttpResponse("Error: No active transaction found.")

    # Kunin ang transaction object
    transaction = get_object_or_404(Transaction, id=transaction_id, status='open')
    
    # 2. Kunin ang Payment Data mula sa URL
    # Kasama na rito ang ref_num para sa Online Wallets
    payment_method = request.GET.get('method', 'Cash')
    raw_received = request.GET.get('received', 0)
    ref_num = request.GET.get('ref_num', '').strip()

    try:
        amount_received = float(raw_received)
    except ValueError:
        amount_received = 0.0

    try:
        with db_transaction.atomic():
            # 3. Stock Deduction Logic
            items_to_deduct = transaction.cart_items.all()
            
            for item in items_to_deduct:
                product = item.inventory_item 
                
                if product.quantity >= item.quantity:
                    product.quantity -= item.quantity
                    product.save()
                else:
                    return HttpResponse(f"Insufficient stock for {product.item_name}!")

            # 4. I-finalize ang Transaction Details
            transaction.status = 'completed'
            transaction.payment_method = payment_method

            if payment_method == 'Online Wallet' and not ref_num:
             return HttpResponse("Error: Reference Number is required for Online Wallet payments.", status=400)
            
            # I-save ang Reference Number kung meron
            if hasattr(transaction, 'reference_number'):
                transaction.reference_number = ref_num
            
            # I-save ang amount received (kung may field ka para rito)
            if hasattr(transaction, 'amount_received'):
                transaction.amount_received = amount_received
            
            transaction.date_completed = timezone.now()
            transaction.save()

            # 5. Calculate Change para sa Template
            change = amount_received - float(transaction.total_amount)

            # 6. Clear session para sa next customer
            if 'transaction_id' in request.session:
                del request.session['transaction_id']

        # 7. Render Receipt
        context = {
            'transaction': transaction,
            'amount_received': amount_received,
            'change': change,
            'ref_num': ref_num, # Ipadala ito para sa thermal print logic
            'cart_items': items_to_deduct 
        }

        return render(request, 'point_of_sale/receipts/thermal_print.html', context)

    except Exception as e:
        return HttpResponse(f"Error: {str(e)}")

def void_transaction(request):
    # This finds the current active cart and cancels it
    Transaction.objects.filter(
        status='open', 
        processed_by=request.user if request.user.is_authenticated else None
    ).update(status='voided')
    
    return redirect('point_of_sale:pos_index')

def reset_transaction(request):
    # This finds the 'open' transaction and marks it as voided/cancelled
    Transaction.objects.filter(
        status='open', 
        processed_by=request.user if request.user.is_authenticated else None
    ).update(status='voided')
    
    return redirect('point_of_sale:pos_index')

def add_by_barcode(request):
    barcode = request.GET.get('barcode')
    
    # Try to find the product by its barcode
    product = InventoryItem.objects.filter(barcode_id=barcode).first()
    
    if not product:
        return JsonResponse({'status': 'error', 'message': f'Product with barcode {barcode} not found!'})
    
    # Get or create the open transaction
    transaction, created = Transaction.objects.get_or_create(
        status='open', 
        processed_by=request.user if request.user.is_authenticated else None
    )
    
    # Get or create the item in the transaction
    item, item_created = TransactionItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'quantity': 1,
            'subtotal': product.price
        }
    )
    
    # If it was already in the cart, increase quantity
    if not item_created:
        item.quantity += 1
        item.save()
    
    transaction.calculate_totals() 
    
    return JsonResponse({'status': 'success'})
