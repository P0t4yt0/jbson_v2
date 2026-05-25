from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from django.db.models import Q, F, ProtectedError
from django.contrib import messages # IDINAGDAG NATIN ITO PARA SA NOTIFICATIONS
from .models import InventoryItem, Category, Supplier
from decimal import Decimal
import random
import barcode
from .models import InventoryItem
from .models import Supplier, PurchaseOrder, PurchaseOrderItem, InventoryItem
from .models import Supplier # <-- Make sure Supplier is imported
from django.db.models import RestrictedError
from activity_log.utils import log_system_activity
from django.db.models import Sum, F, DecimalField
from django.utils import timezone
from datetime import timedelta
from django.db.models.functions import Coalesce
from django.db.models import Q, F, Sum, Count, ProtectedError, DecimalField
from django.db.models.functions import Coalesce
from point_of_sale.models import Transaction, TransactionItem
from django.db import transaction

from point_of_sale.models import Transaction
from inventory.models import InventoryItem, PurchaseOrder
from billing_payment.models import SalesReturn, Invoice
from security.models import EmployeeProfile
from reports_analytics.models import Expense # Assuming you have this based on your migrations!
from django.db.models import F

def inventory_list(request):
    """Displays all items in the inventory with their ABC status and filters."""
    
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', '')
    low_stock = request.GET.get('low_stock', '')
    priority = request.GET.get('priority', '')
    sort_query = request.GET.get('sort', '')
    supplier_id = request.GET.get('supplier', '')

    # Always define items first
    items = InventoryItem.objects.all()

    # 1. Search
    if search_query:
        items = items.filter(
            Q(item_name__icontains=search_query) |
            Q(barcode_id__icontains=search_query)
        )

    # 2. Category
    if category_id:
        items = items.filter(category_id=category_id)

    # 3. Priority
    if priority:
        items = items.filter(abc_classification=priority)

    # 4. Low Stock
    if low_stock == 'on':
        items = items.filter(quantity__lte=F('reorder_point'))

    # 5. Supplier
    if supplier_id:
        items = items.filter(supplier_id=supplier_id)

    # 6. Sorting (applied last)
    if sort_query == 'supplier':
        items = items.order_by('supplier__name', 'abc_classification', '-id')
    elif sort_query == '-supplier':
        items = items.order_by('-supplier__name', 'abc_classification', '-id')
    else:
        items = items.order_by('abc_classification', '-id')

    categories = Category.objects.all()

    context = {
        'items': items,
        'categories': categories,
        'suppliers': Supplier.objects.filter(is_active=True).order_by('name'),
        'search_query': search_query,
        'selected_category': category_id,
        'low_stock': low_stock,
        'selected_priority': priority,
        'current_sort': sort_query,
        'selected_supplier': supplier_id,
    }
    return render(request, 'inventory/product_list.html', context)



def run_abc_analysis(request):
    items = InventoryItem.objects.all()
    
    # --- STEP 1: PRE-CALCULATION LOGIC ---
    item_value_pairs = []
    total_store_value = Decimal('0')

    for item in items:
        actual_sales = getattr(item, 'actual_sales_count', 0)
        manual_est = int(item.annual_demand or 0)
        
        effective_demand = actual_sales if actual_sales > 0 else manual_est
        
        unit_cost = Decimal(str(item.unit_cost or 0))
        item_value = unit_cost * effective_demand
        
        item_value_pairs.append((item, item_value))
        total_store_value += item_value

    if total_store_value == 0:
        return redirect('inventory:inventory_list')

    # --- STEP 2: SORTING & CLASSIFICATION ---
    item_value_pairs.sort(key=lambda x: x[1], reverse=True)

    running_sum = Decimal('0')
    for item, item_value in item_value_pairs:
        running_sum += item_value
        cumulative_percentage = (running_sum / total_store_value) * 100

        if cumulative_percentage <= 70:
            item.abc_classification = 'A'
        elif cumulative_percentage <= 90:
            item.abc_classification = 'B'
        else:
            item.abc_classification = 'C'
        
        item.save()
    log_system_activity(
            user=request.user,
            action="ABC ANALYSIS",
            description="Executed ABC Inventory Classification analysis and updated item priorities."
        )
    
    return redirect('inventory:inventory_list')

def edit_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    
    if request.method == 'POST':
        # Ginagamit natin yung "or item.<field>" para kung empty yung pinasa sa form, 
        # ire-retain niya yung dating naka-save sa database.
        item.item_name = request.POST.get('item_name') or item.item_name
        item.category_id = request.POST.get('category') or item.category_id
        item.supplier_id = request.POST.get('supplier') or item.supplier_id
        item.quantity = request.POST.get('quantity') or item.quantity
        item.barcode_id = request.POST.get('barcode_id') or item.barcode_id
        
        # Pinalitan natin ang fallback from 0/0.00 to their existing values
        item.price = request.POST.get('price') or item.price
        item.unit_cost = request.POST.get('unit_cost') or item.unit_cost
        item.annual_demand = request.POST.get('annual_demand') or item.annual_demand
        
        # --- NEW ROP FIELDS ---
        item.average_daily_sales = float(request.POST.get('average_daily_sales') or item.average_daily_sales or 0)
        item.max_daily_sales = float(request.POST.get('max_daily_sales') or item.max_daily_sales or 0)
        item.average_lead_time_days = int(request.POST.get('average_lead_time_days') or item.average_lead_time_days or 0)
        item.max_lead_time_days = int(request.POST.get('max_lead_time_days') or item.max_lead_time_days or 0)        # ----------------------

        item.save()
        return redirect('inventory:inventory_list')

    categories = Category.objects.all()
    suppliers = Supplier.objects.filter(is_active=True)
    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })
# SINGLE DELETE VIEW
def delete_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    try:
        item_name = item.item_name
        item.delete()
        messages.success(request, f'Product "{item_name}" deleted successfully.')
    except ProtectedError:
        # Kapag may transaction na yung item, sasaluhin nito yung error
        messages.error(request, f'Cannot delete "{item.item_name}" because it is already linked to existing transactions/sales.')
        
    return redirect('inventory:inventory_list')


# BULK DELETE VIEW
def bulk_delete_products(request):
    if request.method == 'POST':
        ids_string = request.POST.get('product_ids', '')
        if ids_string:
            id_list = ids_string.split(',')
            try:
                # Subukang burahin lahat ng na-check
                deleted_count, _ = InventoryItem.objects.filter(pk__in=id_list).delete()
                log_system_activity(
                    user=request.user,
                    action="BULK DELETE",
                    description=f"Bulk deleted {deleted_count} inventory items."
                )
                messages.success(request, f'Successfully deleted {deleted_count} product(s).')
            except ProtectedError:
                # Kung kahit isa sa na-check ay may transaction, iba-block ng database lahat
                messages.error(request, 'Action failed. Some of the selected products cannot be deleted because they have existing transaction records.')
                
    return redirect('inventory:inventory_list')

def low_stock_view(request):
    """Specifically filters items that are at or below min_stock."""
    low_stock_items = [item for item in InventoryItem.objects.all() if item.is_low_stock]
    return render(request, 'inventory/low_stock.html', {'items': low_stock_items})

def category_list(request):
    """Displays all categories and the items under them. Also handles adding new categories."""
    
    # 1. I-CHECK KUNG MAY NAG-SUBMIT NG ADD CATEGORY FORM
    if request.method == 'POST':
        new_name = request.POST.get('name')
        new_prefix = request.POST.get('prefix')
        
        if new_name and new_prefix:
            # Pwede kang magdagdag ng validation dito kung gusto mo (e.g., check kung existing na)
            # Para iwas error, i-check kung may kapangalan na bago i-save
            if not Category.objects.filter(name=new_name).exists():
                Category.objects.create(name=new_name, prefix=new_prefix)
                messages.success(request, f'Category "{new_name}" successfully added.')
            else:
                messages.error(request, f'Category "{new_name}" already exists.')
        else:
            messages.error(request, 'Error: Category name or prefix is missing.')
            
        # I-refresh ang page para lumabas yung bagong category
        return redirect('inventory:category_list')

    # 2. NORMAL PAGE LOAD (GET REQUEST)
    # prefetch_related makes loading items much faster!
    categories = Category.objects.prefetch_related('items').all()
    return render(request, 'inventory/category_list.html', {'categories': categories})

def edit_category(request, pk):
    """Allows editing the category name only."""
    category = get_object_or_404(Category, pk=pk)
    if request.method == 'POST':
        new_name = request.POST.get('name')
        if new_name:
            category.name = new_name
            category.save()
            messages.success(request, f'Category successfully renamed to "{new_name}".')
    return redirect('inventory:category_list')

def delete_category(request, pk):
    """Deletes a category ONLY if it has no products."""
    category = get_object_or_404(Category, pk=pk)
    try:
        cat_name = category.name
        category.delete()
        messages.success(request, f'Category "{cat_name}" deleted successfully.')
    except ProtectedError:
        # This catches the error automatically because of on_delete=models.PROTECT
        messages.error(request, f'Cannot delete "{category.name}" because there are products currently assigned to it.')
        
    return redirect('inventory:category_list')

import os
from django.conf import settings
import barcode
from barcode.writer import ImageWriter
import random
from django.shortcuts import render

def barcode_module_view(request):
    context = {}
    
    if request.method == 'POST':
        # Generate 480 prefix + 9 random digits
        base_number = f"480{random.randint(100000000, 999999999)}"
        
        # Gagamitin lang natin 'to para kunin yung valid 13-digit code
        EAN = barcode.get_barcode_class('ean13')
        my_barcode = EAN(base_number) # Pansinin: Wala nang ImageWriter!
        
        # Ipasa diretso sa HTML yung number string (e.g., "480123456789X")
        context['barcode_id'] = my_barcode.get_fullcode()

    return render(request, 'inventory/generate_barcode.html', context)

def admin_dashboard_view(request):
    today = timezone.now().date()
    
    # --- 1. GLOBAL DATE FILTER LOGIC ---
    date_filter = request.GET.get('filter', 'all_time')
    if date_filter == 'today': start_date = today
    elif date_filter == 'this_week': start_date = today - timedelta(days=today.weekday())
    elif date_filter == 'this_month': start_date = today.replace(day=1)
    elif date_filter == 'this_year': start_date = today.replace(month=1, day=1)
    else: start_date = None 

    # --- 2. BASE QUERIES ---
    tx_base = Transaction.objects.filter(status__in=['completed', 'paid'])
    po_base = PurchaseOrder.objects.filter(status='received')
    invoice_base = Invoice.objects.all()
    expense_base = None # Will assign dynamically based on import

    # Try to import Expense safely just in case
    try:
        from reports_analytics.models import Expense
        expense_base = Expense.objects.all()
    except ImportError:
        pass

    if start_date:
        tx_base = tx_base.filter(date_created__date__gte=start_date)
        po_base = po_base.filter(order_date__gte=start_date)
        if expense_base is not None: expense_base = expense_base.filter(expense_date__gte=start_date)

    # --- 3. CORE METRICS CALCULATION ---
    total_sales = tx_base.aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
    total_purchase = po_base.aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
    sales_return = SalesReturn.objects.aggregate(t=Coalesce(Sum('total_refund'), Decimal('0.00'), output_field=DecimalField()))['t']
    invoice_due = Invoice.objects.filter(status='unpaid').aggregate(t=Coalesce(Sum('balance_due'), Decimal('0.00'), output_field=DecimalField()))['t']
    
    expenses = Decimal('0.00')
    if expense_base is not None:
        expenses = expense_base.aggregate(t=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()))['t']

    total_outflow = total_purchase + expenses
    net_profit = total_sales - total_outflow - sales_return

    # --- 4. ADVANCED CHART DATA (7-Day Financials) ---
    chart_labels = []
    chart_sales_data = []
    chart_outflow_data = []
    chart_profit_data = []

    for i in range(6, -1, -1):
        current_day = today - timedelta(days=i)
        next_day = current_day + timedelta(days=1) # Create the boundary for "tomorrow"
        
        chart_labels.append(current_day.strftime('%b %d'))
        
        # 1. Fetch Sales (BULLETPROOF: Using >= today and < tomorrow)
        d_sales = Transaction.objects.filter(
            date_created__gte=current_day,
            date_created__lt=next_day,
            status__in=['completed', 'credit']
        ).aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
        
        # 2. Fetch Purchases
        d_purchases = PurchaseOrder.objects.filter(
            status='received', 
            order_date__gte=current_day,
            order_date__lt=next_day
        ).aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
        
        # 3. Fetch Expenses
        d_expenses = Decimal('0.00')
        if expense_base is not None:
            d_expenses = expense_base.filter(
                expense_date__gte=current_day,
                expense_date__lt=next_day
            ).aggregate(t=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()))['t']
            
        d_outflow = d_purchases + d_expenses
        d_profit = d_sales - d_outflow

        chart_sales_data.append(float(d_sales))
        chart_outflow_data.append(float(d_outflow))
        chart_profit_data.append(float(d_profit))

    # --- 5. TOP PRODUCTS DOUGHNUT CHART ---
    # Fetch all items from completed or credit sales
    top_items_base = TransactionItem.objects.filter(transaction__status__in=['completed', 'credit'])
    
    if start_date:
        # THE FIX: Using __gte on the raw datetime bypasses the SQLite date bug!
        top_items_base = top_items_base.filter(transaction__date_created__gte=start_date)

    # Group by item name, sum the quantities, and grab the top 5
    top_products_qs = top_items_base.values('inventory_item__item_name').annotate(total_sold=Sum('quantity')).order_by('-total_sold')[:5]
    
    donut_labels = [p['inventory_item__item_name'] for p in top_products_qs]
    donut_data = [float(p['total_sold']) for p in top_products_qs]

    # --- 6. ACTIONABLE LISTS ---
    low_stock_items = InventoryItem.objects.filter(quantity__lte=F('reorder_point')).order_by('quantity')[:5]
    unpaid_invoices = Invoice.objects.filter(status='unpaid').order_by('due_date')[:5]

    metrics = {
        'total_sales': total_sales,
        'total_outflow': total_outflow,
        'net_profit': net_profit,
        'invoice_due': invoice_due,
        'current_filter': date_filter,
    }

    context = {
        'metrics': metrics,
        'low_stock_items': low_stock_items,
        'top_products': top_products_qs,
        'unpaid_invoices': unpaid_invoices,
        'chart_labels': json.dumps(chart_labels),
        'chart_sales_data': json.dumps(chart_sales_data),
        'chart_outflow_data': json.dumps(chart_outflow_data),
        'chart_profit_data': json.dumps(chart_profit_data),
        'donut_labels': json.dumps(donut_labels),
        'donut_data': json.dumps(donut_data),
    }

    return render(request, 'dashboard/dashboard.html', context)


def delete_user(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('security:register')

    # Hanapin ang user gamit ang tamang tool
    user_to_delete = get_object_or_404(User, id=user_id)
    
    if user_to_delete == request.user:
        messages.error(request, "You cannot delete yourself.")
    else:
        username_deleted = user_to_delete.username
        user_to_delete.delete()

        log_system_activity(
            user=request.user,
            action="DELETE USER",
            description=f"Deleted user account: '{username_deleted}'"
        )
        
        messages.success(request, f"User '{username_deleted}' deleted.")
        
    # Redirect pabalik sa User Management page
    return redirect('security:register')

def supplier_list(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        contact_name = request.POST.get('contact_name')
        phone = request.POST.get('phone')
        email = request.POST.get('email')
        address = request.POST.get('address')
        default_lt = request.POST.get('default_lead_time_days', 7)
        max_lt = request.POST.get('max_lead_time_days', 14)
        
        # Simple check to prevent duplicates
        if Supplier.objects.filter(name__iexact=name).exists():
            messages.error(request, f"Supplier '{name}' already exists.")
        else:
            Supplier.objects.create(
                name=name,
                contact_name=contact_name,
                phone=phone,
                email=email,
                address=address,
                default_lead_time_days=default_lt,
                max_lead_time_days=max_lt
            )
            messages.success(request, f"Supplier '{name}' added successfully!")
            
        return redirect('inventory:supplier_list')

    # Get all suppliers for the table
    suppliers = Supplier.objects.all()
    
    return render(request, 'inventory/supplier_list.html', {
        'suppliers': suppliers
    })


def create_po(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        expected_delivery = request.POST.get('expected_delivery')
        
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_costs = request.POST.getlist('unit_cost[]')
        
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Adviser Fix: If no date is provided, use 7-day fallback
        fallback_date = timezone.now().date() + timezone.timedelta(days=7)
        action = request.POST.get('action')
        po_status = 'pending' if action == 'submit_po' else 'draft'
        
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            expected_delivery=expected_delivery if expected_delivery else fallback_date,
            status=po_status # Officially saving it as an order!
        )
        
        total_amount = Decimal('0.00')
        
        for i in range(len(product_ids)):
            if product_ids[i] and quantities[i] and unit_costs[i]:
                product = get_object_or_404(InventoryItem, id=product_ids[i])
                qty = int(quantities[i])
                cost = Decimal(unit_costs[i])
                
                PurchaseOrderItem.objects.create(
                    purchase_order=po,
                    product=product,
                    quantity_ordered=qty,
                    unit_cost=cost
                )
                total_amount += (qty * cost)
                
        po.total_amount = total_amount
        po.save()

        if po_status == 'draft':
            messages.success(request, f"Draft saved successfully for {supplier.name}.")
            # Send them to the edit page so they can keep working on the draft
            return redirect('inventory:edit_po', po_id=po.id) 
        else:
            messages.success(request, f"Purchase Order {po.po_number} officially generated!")
            return redirect('inventory:create_po')

    # --- GET REQUEST: LOAD FORM OR AUTO-FILL DRAFT ---
    suppliers = Supplier.objects.filter(is_active=True)
    products = InventoryItem.objects.all().order_by('item_name')
    
    auto_supplier_id = None
    auto_items = []
    # Pre-calculate the 7-day default delivery string for the HTML input
    fallback_date_str = (timezone.now().date() + timezone.timedelta(days=7)).strftime('%Y-%m-%d')

    if request.GET.get('auto') == 'true':
        # THE FIX: Exclude items that do not have a supplier assigned
        low_stock_items = InventoryItem.objects.exclude(supplier__isnull=True).annotate(
            incoming_qty=Coalesce(
                Sum(
                    'purchaseorderitem__quantity_ordered',
                    filter=Q(purchaseorderitem__purchase_order__status__in=['pending', 'draft'])
                ),
                0
            )
        ).annotate(
            effective_qty=F('quantity') + F('incoming_qty')
        ).filter(effective_qty__lte=F('reorder_point'))


        if low_stock_items.exists():

                # Check for an existing draft for this supplier first
            existing_draft = PurchaseOrder.objects.filter(
                supplier_id=auto_supplier_id,
                status='draft'
            ).first()
            if existing_draft:
                return redirect('inventory:edit_po', po_id=existing_draft.id)

            # Find the single supplier with the MOST critical low-stock items
            top_supplier = low_stock_items.values('supplier').annotate(c=Count('id')).order_by('-c').first()

            if top_supplier and top_supplier['supplier']:
                auto_supplier_id = int(top_supplier['supplier'])
                existing_draft = PurchaseOrder.objects.filter(
                    supplier_id=auto_supplier_id, status='draft'
                ).first()
                if existing_draft:
                    return redirect('inventory:edit_po', po_id=existing_draft.id)
                items_for_supplier = low_stock_items.filter(supplier_id=auto_supplier_id)

                for item in items_for_supplier:
                    # --- NEW SMART ORDER QUANTITY LOGIC ---
                    avg_sales = float(item.average_daily_sales or 0)
                    safety_stock = getattr(item, 'safety_stock', 0)
                    
                    if avg_sales > 0:
                        # If AI Calibrated: Order enough to last 30 days + keep Safety Stock
                        target_stock_level = int(round(avg_sales * 30)) + safety_stock
                    else:
                        # Fallback if no sales data yet: Just double the ROP
                        target_stock_level = item.reorder_point * 2
                        
                    # Formula: How much we need = Target Stock - (What we currently have + What is already arriving)
                    recommended_qty = target_stock_level - item.effective_qty
                    
                    # Absolute fallback to ensure we don't order 0 or negative numbers
                    if recommended_qty <= 0: 
                        recommended_qty = max(item.reorder_point, 1)

                    cost = float(item.unit_cost or 0)
                    subtotal = recommended_qty * cost


                    auto_items.append({
                        'id': item.id,
                        'name': item.item_name,
                        'qty': recommended_qty,
                        'cost': str(item.unit_cost),
                        'subtotal': f"{subtotal:.2f}" # Dito nakukuha ang subtotal
                    })

                supplier_obj = Supplier.objects.get(id=auto_supplier_id)
                messages.info(request, f"Draft auto-filled for {supplier_obj.name}. Items already pending delivery were ignored. Please review and Save.")
            else:
                # NEW: Tell the user if the logic failed to find a supplier
                messages.warning(request, "Low stock items found, but they don't have a Supplier assigned! Please edit your products and assign a supplier.")
        else:
            messages.success(request, "Inventory is healthy or all low-stock items are already on their way!")

    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')

    # THE FIX: Exclude items that do not have a supplier assigned here as well
    pending_draft_count = InventoryItem.objects.exclude(supplier__isnull=True).annotate(
    incoming_qty=Coalesce(
        Sum(
            'purchaseorderitem__quantity_ordered',
            filter=Q(purchaseorderitem__purchase_order__status__in=['pending', 'draft'])
        ),
        0
    )
).annotate(
    effective_qty=F('quantity') + F('incoming_qty')
).filter(effective_qty__lte=F('reorder_point')).values('supplier').distinct().count()



    return render(request, 'inventory/create_po.html', {
        'suppliers': suppliers,
        'products': products,
        'auto_supplier_id': auto_supplier_id,
        'auto_items': auto_items,
        'fallback_date_str': fallback_date_str,
        'purchase_orders': purchase_orders,
        'pending_draft_count': pending_draft_count
    })

def po_list(request):
    # Fetch all Purchase Orders, ordered by newest first
    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')
    
    return render(request, 'inventory/po_list.html', {
        'purchase_orders': purchase_orders
    })

@transaction.atomic
def receive_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    # Safety check: Only process if it's currently pending
    if po.status != 'pending':
        messages.error(request, "This order has already been processed or cancelled.")
        return redirect('inventory:create_po')
        
    for item in po.items.all():
        product = item.product
        
        # --- SAFE COSTING: Weighted Average Cost (WAC) ---
        current_qty = Decimal(product.quantity)
        ordered_qty = Decimal(item.quantity_ordered)
        
        current_total_value = current_qty * product.unit_cost
        new_delivery_value = ordered_qty * item.unit_cost
        
        new_total_quantity = current_qty + ordered_qty
        
        if new_total_quantity > 0:
            new_average_cost = (current_total_value + new_delivery_value) / new_total_quantity
            product.unit_cost = round(new_average_cost, 2)
            
        # Add the new stock
        product.quantity += item.quantity_ordered
        product.save()
        
        # Mark the PO item as fully received
        item.quantity_received = item.quantity_ordered
        item.save()
        
    # Mark the entire Purchase Order as complete
    po.status = 'received'
    po.save()

    log_system_activity(
        user=request.user,
        action="RECEIVE PO",
        description=f"Received delivery for PO {po.po_number}. Inventory stock and average costs updated."
    )
    messages.success(request, f"Delivery for {po.po_number} received! Inventory stock and costs have been safely updated.")
    return redirect('inventory:create_po')


def edit_supplier(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)
    
    if request.method == 'POST':
        supplier.name = request.POST.get('name')
        supplier.contact_name = request.POST.get('contact_name')
        supplier.phone = request.POST.get('phone')
        supplier.email = request.POST.get('email')
        supplier.address = request.POST.get('address')
        
        # Save the new logistics fields
        supplier.default_lead_time_days = request.POST.get('default_lead_time_days', 7)
        supplier.max_lead_time_days = request.POST.get('max_lead_time_days', 14)
        
        supplier.save()
        
        # --- NEW LOGIC: INSTANTLY UPDATE ALL LINKED PRODUCTS ---
        # This loops through every product connected to this supplier
        # and triggers the save() method, which forces the ROP math to recalculate immediately!
        for product in supplier.inventoryitem_set.all():
            product.save()
        # -------------------------------------------------------

        messages.success(request, f"Supplier '{supplier.name}' updated! All associated product reorder points have been instantly recalculated.")
        return redirect('inventory:supplier_list')
        
    return render(request, 'inventory/edit_supplier.html', {
        'supplier': supplier
    })


def delete_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Soft Delete: Just mark them as inactive instead of wiping the data!
        supplier.is_active = False
        supplier.save()

        log_system_activity(
            user=request.user,
            action="ARCHIVE SUPPLIER",
            description=f"Archived supplier '{supplier.name}'"
        )
        messages.success(request, f"Supplier '{supplier.name}' has been archived and hidden from the system.")
            
    return redirect('inventory:supplier_list')

def unarchive_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Restore the supplier!
        supplier.is_active = True
        supplier.save()

        log_system_activity(
            user=request.user,
            action="RESTORE SUPPLIER",
            description=f"Restored archived supplier '{supplier.name}'"
        )
        messages.success(request, f"Supplier '{supplier.name}' has been restored and is active again.")
            
    return redirect('inventory:supplier_list')

def edit_po(request, po_id):
    """Loads a specific Purchase Order into the Hub for Editing/Viewing."""
    target_po = get_object_or_404(PurchaseOrder, id=po_id)
    
    if request.method == 'POST':
        # Safety Lock: We only allow edits if the items haven't been delivered yet!
        if target_po.status == 'draft':
            supplier_id = request.POST.get('supplier')
            if supplier_id:
                target_po.supplier = get_object_or_404(Supplier, id=supplier_id)
                
            expected_delivery = request.POST.get('expected_delivery')
            if expected_delivery:
                target_po.expected_delivery = expected_delivery
            
            # Rebuild the items list completely so they can add/remove rows easily
            target_po.items.all().delete()
            
            product_ids = request.POST.getlist('product_id[]')
            quantities = request.POST.getlist('quantity[]')
            unit_costs = request.POST.getlist('unit_cost[]')
            
            total_amount = Decimal('0.00')
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i] and unit_costs[i]:
                    product = get_object_or_404(InventoryItem, id=product_ids[i])
                    qty = int(quantities[i])
                    cost = Decimal(unit_costs[i])
                    
                    PurchaseOrderItem.objects.create(
                        purchase_order=target_po,
                        product=product,
                        quantity_ordered=qty,
                        unit_cost=cost
                    )
                    total_amount += (qty * cost)
            
            target_po.total_amount = total_amount

            action = request.POST.get('action')
            if action == 'submit_po':
                target_po.status = 'pending'

            target_po.save()

            if target_po.status == 'pending':
                messages.success(request, f"Order {target_po.po_number} has been officially submitted!")
                return redirect('inventory:create_po') # Back to main hub
            else:
                messages.success(request, f"Draft {target_po.po_number} successfully updated!")
                return redirect('inventory:edit_po', po_id=target_po.id) # Stay on draft
        else: # NEW: Add an error message if they somehow try to force a save
            messages.error(request, "This order is already being processed and cannot be edited.")
        return redirect('inventory:edit_po', po_id=target_po.id)

    # GET Request: Load the UI
    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')
    suppliers = Supplier.objects.filter(is_active=True)
    products = InventoryItem.objects.all().order_by('item_name')
    
    # Safely format the date for the HTML date picker
    formatted_date = target_po.expected_delivery.strftime('%Y-%m-%d') if target_po.expected_delivery else ''

    # Calculate how many unique suppliers currently have low stock (ignoring pending orders)
    pending_draft_count = InventoryItem.objects.exclude(supplier__isnull=True).annotate(
    incoming_qty=Coalesce(
        Sum(
            'purchaseorderitem__quantity_ordered',
            filter=Q(purchaseorderitem__purchase_order__status__in=['pending', 'draft'])
        ),
        0
    )
).annotate(
    effective_qty=F('quantity') + F('incoming_qty')
).filter(effective_qty__lte=F('reorder_point')).values('supplier').distinct().count()



    return render(request, 'inventory/create_po.html', {
        'purchase_orders': purchase_orders,
        'suppliers': suppliers,
        'products': products,
        'target_po': target_po,
        'edit_mode': True,
        'formatted_date': formatted_date,
        'pending_draft_count': pending_draft_count # <--- Add this new variable to the list!
    })

def delete_po(request, po_id):
    """Cancels a drafted or pending Purchase Order instead of deleting it."""
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    if po.status in ['draft', 'pending']:
        po_num = po.po_number
        po.status = 'cancelled'
        po.save()
        
        log_system_activity(
            user=request.user,
            action="CANCEL PO",
            description=f"Cancelled Purchase Order {po_num}."
        )
        messages.success(request, f"Order {po_num} has been successfully cancelled.")
    else:
        messages.error(request, "You cannot cancel a completed delivery.")
        
    return redirect('inventory:create_po')


def auto_calibrate_rop(request):
    """
    Auto-Learning Feature: Scans POS transactions from the last 30 days,
    computes the real Average and Max Daily Sales, and updates the ROP automatically.
    """
    # 1. Kunin ang petsa eksaktong 30 days ago
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    # 2. Kunin lahat ng items sa inventory
    items = InventoryItem.objects.all()
    
    updated_count = 0
    
    for item in items:
        # Kunin lahat ng benta ng specific item na ito from the last 30 days
        sales = TransactionItem.objects.filter(
            inventory_item=item,
            transaction__status__in=['completed', 'paid'],
            transaction__date_created__gte=thirty_days_ago
        )
        
        # I-group ang sales per day gamit ang dictionary (Para iwas SQLite bug)
        daily_sales_dict = {}
        for sale in sales:
            date_str = sale.transaction.date_created.strftime('%Y-%m-%d')
            if date_str not in daily_sales_dict:
                daily_sales_dict[date_str] = 0
            daily_sales_dict[date_str] += sale.quantity
            
        # Kung may benta in the last 30 days, i-compute ang auto-learn data!
        if daily_sales_dict:
            total_sales = sum(daily_sales_dict.values())
            
            # Average Daily Sales (Total na benta hatiin sa 30 days)
            item.average_daily_sales = float(total_sales) / 30.0
            
            # Max Daily Sales (Pinakamataas na benta sa isang araw)
            item.max_daily_sales = float(max(daily_sales_dict.values()))
            
            # I-save para mag-trigger yung formula sa models.py
            item.save()
            updated_count += 1
            
    # I-log sa system at magpakita ng success message
    log_system_activity(
        user=request.user,
        action="AUTO CALIBRATE",
        description=f"System auto-calibrated Reorder Points for {updated_count} active items based on 30-day POS history."
    )
    
    messages.success(request, f"Inventory Intelligence synced! ROP and Safety Stocks for {updated_count} items have been auto-calibrated based on your last 30 days of sales operations.")
    
    return redirect('inventory:inventory_list')