from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Transaction, TransactionItem
from inventory.models import InventoryItem
from django.shortcuts import redirect
from django.shortcuts import render, redirect, get_object_or_404
from inventory.models import InventoryItem
from inventory.models import InventoryItem, Category
from .models import Transaction, TransactionItem

def pos_view(request):
    # Get products and categories
    products = InventoryItem.objects.all()
    categories = Category.objects.all() # Fetch all dynamic categories
    
    transaction, created = Transaction.objects.get_or_create(
        status='open',
        processed_by=request.user if request.user.is_authenticated else None
    )
    cart_items = transaction.items.all()

    context = {
        'products': products,
        'categories': categories, # Add this to the context
        'transaction': transaction,
        'cart_items': cart_items,
    }
    
    return render(request, 'point_of_sale/pos.html', context)

def add_to_cart(request):
    product_id = request.GET.get('product_id')
    product = get_object_or_404(InventoryItem, id=product_id)
    
    # Get or create the open transaction
    transaction, created = Transaction.objects.get_or_create(
        status='open', 
        processed_by=request.user if request.user.is_authenticated else None
    )
    
    # Get or create the specific item in that transaction
    item, item_created = TransactionItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'quantity': 1,
            'subtotal': product.price
        }
    )
    
    if not item_created:
        item.quantity += 1
        # item.save() will trigger TransactionItem's save() which calculates subtotal
        item.save()
    
    # CRITICAL STEP: Tell the transaction to update its Grand Total
    transaction.calculate_totals() 
    
    return JsonResponse({'status': 'success'})

def process_payment(request):
    method = request.GET.get('method', 'Cash')
    received = request.GET.get('received', 0)
    
    transaction = Transaction.objects.filter(status='open').first()
    
    if transaction:
        transaction.payment_method = method
        transaction.amount_received = float(received)
        # You can calculate change here too:
        transaction.change_amount = float(received) - float(transaction.total_amount)
        
        transaction.status = 'completed'
        transaction.save()
        # ... inventory update logic ...
        
    return render(request, 'point_of_sale/receipts/thermal_print.html', {'transaction': transaction})

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
