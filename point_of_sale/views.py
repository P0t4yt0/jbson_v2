import json
import traceback
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import F, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import barcode
from activity_log.utils import log_system_activity
from billing_payment.models import Customer, Invoice, InvoiceItem, Payment
from inventory.models import Category, InventoryItem
from notifications.models import Notification
from .models import Transaction, TransactionItem
from django.http import HttpResponseForbidden

@login_required
def pos_view(request):
    if getattr(request.user, 'role', '').lower() == 'admin' or request.user.is_superuser:
        return HttpResponseForbidden("Security Alert: Administrators are not allowed to access the Checkout module to prevent internal fraud.")
    
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

@login_required
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
    
    # UPDATED: Nagbabalik na ngayon ng detailed data para sa AJAX/Fetch
    return JsonResponse({
        'status': 'success',
        'is_new_item': created,
        'item_id': cart_item.id,
        'item_name': product.item_name,
        'quantity': cart_item.quantity,
        'unit_price': float(cart_item.unit_price),
        'item_subtotal': float(cart_item.subtotal),
        'transaction_total': float(transaction.total_amount)
    })

@csrf_exempt
def update_cart_item(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            item_id = data.get('item_id')
            action = data.get('action')
            new_qty = data.get('quantity')
            
            try:
                cart_item = TransactionItem.objects.get(id=item_id)
            except TransactionItem.DoesNotExist:
                return JsonResponse({'status': 'success'})
                
            transaction = cart_item.transaction
            
            if action == 'increase':
                cart_item.quantity += 1
            elif action == 'decrease':
                if cart_item.quantity > 1:
                    cart_item.quantity -= 1
                else:
                    action = 'remove'
            elif action == 'set':
                try:
                    qty_val = int(new_qty)
                    if qty_val > 0:
                        cart_item.quantity = qty_val
                    else:
                        action = 'remove'
                except (ValueError, TypeError):
                    pass
            
            # UPDATED: I-save muna ang values bago i-delete para maipasa sa frontend
            item_qty = 0
            item_sub = 0
            
            if action == 'remove':
                cart_item.delete()
            else:
                cart_item.subtotal = cart_item.quantity * cart_item.unit_price
                cart_item.save()
                item_qty = cart_item.quantity
                item_sub = float(cart_item.subtotal)
            
            remaining_items = TransactionItem.objects.filter(transaction=transaction)
            new_total = sum(item.subtotal for item in remaining_items)
                
            transaction.total_amount = new_total
            transaction.save()
            
            # UPDATED: Nagbabalik na ng detailed data para sa DOM manipulation
            return JsonResponse({
                'status': 'success',
                'action': action,
                'item_id': item_id,
                'quantity': item_qty,
                'item_subtotal': item_sub,
                'transaction_total': float(new_total)
            })
            
        except Exception as e:
            print(f"POS UPDATE ERROR: {str(e)}") 
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@login_required
def add_by_barcode(request):
    barcode_param = request.GET.get('barcode')
    product = InventoryItem.objects.filter(barcode_id=barcode_param).first()

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
    
    # UPDATED: Same format with add_to_cart para madali i-handle sa JS
    return JsonResponse({
        'status': 'success',
        'is_new_item': created,
        'item_id': item.id,
        'item_name': product.item_name,
        'quantity': item.quantity,
        'unit_price': float(item.unit_price),
        'item_subtotal': float(item.subtotal),
        'transaction_total': float(transaction.total_amount)
    })

@login_required
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
            for item in transaction.sold_items.all():
                if item.inventory_item.quantity < item.quantity:
                    messages.error(request, f"Insufficient stock for {item.inventory_item.item_name}. Only {item.inventory_item.quantity} left.")
                    return redirect('point_of_sale:pos_index')

            for item in transaction.sold_items.all():
                product = item.inventory_item
                product.quantity -= item.quantity
                product.save()

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

                try:
                    terms = int(customer.payment_terms)
                except (ValueError, TypeError):
                    terms = 30
                
                if terms == 60:
                    interest_rate = Decimal('0.02')
                elif terms == 90:
                    interest_rate = Decimal('0.04')
                else:
                    interest_rate = Decimal('0.00')

                interest_amount = transaction.subtotal * interest_rate
                new_total = transaction.subtotal + interest_amount

                if customer.credit_balance + new_total > customer.credit_limit:
                    messages.error(request, "Credit limit exceeded including interest.")
                    return redirect('point_of_sale:pos_index')

                transaction.payment_method = 'credit'
                transaction.customer = customer
                transaction.status = 'credit'
                transaction.total_amount = new_total 
                transaction.date_completed = timezone.now()
                transaction.save()

                invoice = Invoice.objects.create(
                    transaction=transaction,
                    customer=customer,
                    total_amount=transaction.total_amount,
                    balance_due=transaction.total_amount,
                    interest_amount=interest_amount, 
                    status='unpaid' 
                )

                customer.credit_balance += transaction.total_amount
                customer.save()

            else:
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
                if customer_id and customer_id not in ['None', '']:
                    customer_obj = Customer.objects.filter(id=customer_id).first()

                invoice = Invoice.objects.create(
                    transaction=transaction,
                    customer=customer_obj, 
                    total_amount=transaction.total_amount,
                    balance_due=0, 
                    interest_amount=0,
                    status='paid'
                )

            if invoice:
                for item in transaction.sold_items.all():
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product_name=item.inventory_item.item_name,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        subtotal=item.subtotal
                    )
                
                if method == 'Trade Credit' and invoice.interest_amount > 0:
                    interest_percentage = "2%" if int(customer.payment_terms) == 60 else "4%"
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product_name=f"Trade Credit Interest ({interest_percentage})",
                        quantity=1,
                        unit_price=invoice.interest_amount,
                        subtotal=invoice.interest_amount
                    )

            payment_type = "Trade Credit" if method == 'Trade Credit' else method
            
            log_system_activity(
                user=request.user,
                action="POS TRANSACTION",
                description=f"Processed POS transaction {transaction.transaction_ref} via {payment_type} (Total: ₱{transaction.total_amount})"
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
        traceback.print_exc()
        messages.error(request, f"Transaction Error: {str(e)}")
        return redirect('point_of_sale:pos_index')

@login_required
def void_transaction(request):
    transaction_id = request.session.get('transaction_id')
    
    if transaction_id:
        try:
            transaction = Transaction.objects.get(id=transaction_id, status='open')
            transaction.delete()
            del request.session['transaction_id']
            messages.success(request, "Order has been successfully voided.")
        except Transaction.DoesNotExist:
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

@login_required
def reset_transaction(request):
    return void_transaction(request)

@login_required
def quotation_list_view(request):
    search_query = request.GET.get('search', '').strip()
    start_date = request.GET.get('start_date', '').strip()
    end_date = request.GET.get('end_date', '').strip()
    per_page = request.GET.get('per_page', 10)

    quotations = Transaction.objects.filter(status='quotation').order_by('-date_created')

    if search_query:
        quotations = quotations.filter(Q(transaction_ref__icontains=search_query))

    if start_date:
        quotations = quotations.filter(date_created__date__gte=start_date)
    
    if end_date:
        quotations = quotations.filter(date_created__date__lte=end_date)

    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(quotations, per_page)
    page_number = request.GET.get('page', 1)
    quotations_page = paginator.get_page(page_number)

    context = {
        'quotations': quotations_page,
        'search_query': search_query,
        'start_date': start_date,
        'end_date': end_date,
        'per_page': per_page,
    }
    
    return render(request, 'point_of_sale/quotation_list.html', context)

@login_required
def save_as_quotation(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, status='open')
    
    if not transaction.sold_items.exists():
        messages.error(request, "No items in cart! Unable to save as quotation.")
        return redirect('point_of_sale:pos_index')

    transaction.status = 'quotation'
    transaction.save()

    log_system_activity(
        user=request.user,
        action="SAVE QUOTATION",
        description=f"Saved open transaction as Quotation Ref: {transaction.transaction_ref}"
    )
    messages.success(request, f"Quotation {transaction.transaction_ref} saved successfully!")
    return redirect('point_of_sale:pos_index')

@login_required
def load_quotation_to_pos(request, transaction_id):
    if getattr(request.user, 'role', '').lower() == 'admin' or request.user.is_superuser:
        return HttpResponseForbidden("Security Alert: Administrators cannot convert quotations into active checkout transactions.")
    transaction = get_object_or_404(Transaction, id=transaction_id, status='quotation')
    transaction.status = 'open'
    transaction.save()

    log_system_activity(
        user=request.user,
        action="LOAD QUOTATION",
        description=f"Loaded Quotation Ref: {transaction.transaction_ref} into POS cart"
    )
    
    request.session['transaction_id'] = transaction.id
    messages.success(request, f"Quotation {transaction.transaction_ref} loaded to POS!")
    return redirect('point_of_sale:pos_index')

@login_required
def get_quotation_details(request):
    ref_number = request.GET.get('ref')
    
    try:
        transaction = Transaction.objects.get(transaction_ref=ref_number)
        items = TransactionItem.objects.filter(transaction=transaction)
        
        items_data = []
        for item in items:
            computed_price = float(item.subtotal) / int(item.quantity) if int(item.quantity) > 0 else 0
            items_data.append({
                'name': item.inventory_item.item_name,
                'price': computed_price,
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
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@login_required
def reprint_receipt(request, txn_id):
    transaction = get_object_or_404(Transaction, id=txn_id)
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

@login_required
def print_quotation(request, transaction_id):
    transaction = get_object_or_404(Transaction, id=transaction_id, status='quotation')
    
    context = {
        'transaction': transaction,
    }
    
    return render(request, 'point_of_sale/receipts/print_quotation.html', context)