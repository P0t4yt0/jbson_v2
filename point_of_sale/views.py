import json

# 1. Django Shortcuts
from django.shortcuts import render, redirect, get_object_or_404

# 2. HTTP Responses
from django.http import JsonResponse, HttpResponse

# 3. Database Transactions
from django.db import transaction as db_transaction

# 4. POS Models
from .models import Transaction, TransactionItem, CartItem

# 5. Inventory Models
from inventory.models import InventoryItem, Category

# 6. Billing / Credit Models
from billing_payment.models import Customer, Invoice, Payment


from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages


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

    cart_items = transaction.cart_items.all()

    return render(request, 'point_of_sale/pos.html', {
        'products': products,
        'categories': categories,
        'credit_customers': credit_customers,
        'transaction': transaction,
        'cart_items': cart_items,
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

    cart_item, created = CartItem.objects.get_or_create(
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
            cart_item = CartItem.objects.get(id=data.get('item_id'))
            action = data.get('action')

            if action == 'increase':
                cart_item.quantity += 1
            elif action == 'decrease':
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                else:
                    cart_item.delete()
                    return JsonResponse({'status': 'success'})
            elif action == 'remove':
                cart_item.delete()
                return JsonResponse({'status': 'success'})

            cart_item.subtotal = cart_item.quantity * cart_item.unit_price
            cart_item.save()
            cart_item.transaction.calculate_totals()

            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
        

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
    received = float(request.GET.get('received', 0))
    ref_num = request.GET.get('ref_num', '').strip()
    customer_id = request.GET.get('customer_id')

    try:
        with db_transaction.atomic():

            # STOCK DEDUCTION
            for item in transaction.cart_items.all():
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
            'cart_items': transaction.cart_items.all(),
            'amount_received': received,
            'change': received - float(transaction.total_amount),
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

