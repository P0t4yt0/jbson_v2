from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Transaction, TransactionItem
from inventory.models import InventoryItem
from django.shortcuts import redirect
from django.shortcuts import render, redirect, get_object_or_404
from inventory.models import InventoryItem
from .models import Transaction, TransactionItem

def pos_view(request):
    # 1. Get all products for the left-side grid
    products = InventoryItem.objects.all()
    
    # 2. Get or create an 'open' transaction for the current session
    # This ensures there is always a "cart" ready to receive items
    transaction, created = Transaction.objects.get_or_create(
        status='open',
        processed_by=request.user if request.user.is_authenticated else None
    )
    
    # 3. Get the items currently in this transaction to show in the 'Order List'
    cart_items = transaction.items.all()

    context = {
        'products': products,
        'transaction': transaction,
        'cart_items': cart_items,
    }
    
    return render(request, 'point_of_sale/pos.html', context)

def add_to_cart(request):
    product_id = request.GET.get('product_id')
    product = get_object_or_404(InventoryItem, id=product_id)
    
    # Find the current open transaction
    transaction, _ = Transaction.objects.get_or_create(
        status='open', 
        processed_by=request.user if request.user.is_authenticated else None
    )
    
    # Create or update the TransactionItem
    item, created = TransactionItem.objects.get_or_create(
        transaction=transaction,
        inventory_item=product,
        defaults={
            'unit_price': product.price,
            'subtotal': product.price
        }
    )
    
    if not created:
        item.quantity += 1
        item.save()
    
    # Recalculate the Grand Total
    transaction.calculate_totals()
    
    return JsonResponse({'status': 'success'})

def process_payment(request):
    transaction = Transaction.objects.filter(status='open', processed_by=request.user).first()
    
    if not transaction or transaction.items.count() == 0:
        return JsonResponse({'status': 'error', 'message': 'Cart is empty'})

    # 1. Update Inventory and Sales Counts
    for item in transaction.items.all():
        product = item.inventory_item
        product.quantity -= item.quantity # Deduct Stock
        
        # This feeds your ABC Analysis!
        if hasattr(product, 'actual_sales_count'):
            product.actual_sales_count += item.quantity 
        
        product.save()

    # 2. Finalize Transaction
    transaction.status = 'completed'
    transaction.save()

    return JsonResponse({'status': 'success', 'message': 'Payment successful!'})

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