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

def inventory_list(request):
    """Displays all items in the inventory with their ABC status and filters."""
    
    # Naka-sort alphabetically para laging nasa taas ang Class A
    items = InventoryItem.objects.all().order_by('abc_classification', '-id')
    categories = Category.objects.all()

    # Kunin ang mga GET parameters
    search_query = request.GET.get('search', '')
    category_id = request.GET.get('category', '')
    low_stock = request.GET.get('low_stock', '')
    priority = request.GET.get('priority', '') # BAGONG PARAMETER

    # 1. Search Logic
    if search_query:
        items = items.filter(
            Q(item_name__icontains=search_query) | 
            Q(barcode_id__icontains=search_query)
        )
    
    # 2. Category Filter
    if category_id:
        items = items.filter(category_id=category_id)

    # 3. Priority Level Filter
    if priority:
        items = items.filter(abc_classification=priority)

    # 4. Low Stocks Filter
    if low_stock == 'on':
        items = items.filter(quantity__lte=F('reorder_point'))

    context = {
        'items': items,
        'categories': categories,
        'search_query': search_query,
        'selected_category': category_id,
        'low_stock': low_stock,
        'selected_priority': priority, # IPAPASA SA TEMPLATE
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
        
        item.save()
        return redirect('inventory:inventory_list')

    categories = Category.objects.all()
    suppliers = Supplier.objects.filter(is_active=True) # <-- Change this back!
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
    """Displays all categories and the items under them."""
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
    LOW_STOCK_THRESHOLD = 10
    
    # Gamitin ang InventoryItem imbes na Product
    # At siguraduhin na 'quantity' ang field name sa models.py mo
    low_stock_items = InventoryItem.objects.filter(quantity__lte=LOW_STOCK_THRESHOLD).order_by('quantity')
    
    context = {
        'low_stock_items': low_stock_items,
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
        
        # Simple check to prevent duplicates
        if Supplier.objects.filter(name__iexact=name).exists():
            messages.error(request, f"Supplier '{name}' already exists.")
        else:
            Supplier.objects.create(
                name=name,
                contact_name=contact_name,
                phone=phone,
                email=email,
                address=address
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
        
        # Django's getlist() grabs all the items from our dynamic HTML table
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_costs = request.POST.getlist('unit_cost[]')
        
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # 1. Create the main Purchase Order record
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            expected_delivery=expected_delivery if expected_delivery else None,
            status='pending' # Setting to pending since we are officially ordering it
        )
        
        total_amount = Decimal('0.00')
        
        # 2. Loop through the arrays and create the individual items
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
                
        # 3. Update the grand total and save
        po.total_amount = total_amount
        po.save()
        
        messages.success(request, f"Purchase Order {po.po_number} created successfully for {supplier.name}!")
        return redirect('inventory:supplier_list') # Redirecting to suppliers for now

    # GET request: Load the form with available suppliers and items
    suppliers = Supplier.objects.all()
    products = InventoryItem.objects.all().order_by('item_name')
    
    return render(request, 'inventory/create_po.html', {
        'suppliers': suppliers,
        'products': products
    })

def po_list(request):
    # Fetch all Purchase Orders, ordered by newest first
    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')
    
    return render(request, 'inventory/po_list.html', {
        'purchase_orders': purchase_orders
    })

def receive_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    # Safety check: Only process if it's currently pending
    if po.status != 'pending':
        messages.error(request, "This order has already been processed or cancelled.")
        return redirect('inventory:po_list')
        
    # The Magic: Loop through the PO items and update the main inventory!
    for item in po.items.all():
        product = item.product
        
        # 1. Add the new stock to the current quantity
        product.quantity += item.quantity_ordered
        
        # 2. Update the system's unit cost to the latest supplier price
        product.unit_cost = item.unit_cost 
        
        product.save()
        
        # 3. Mark the PO item as fully received
        item.quantity_received = item.quantity_ordered
        item.save()
        
    # Mark the entire Purchase Order as complete
    po.status = 'received'
    po.save()
    
    messages.success(request, f"Delivery for {po.po_number} received! Inventory stock and costs have been updated.")
    return redirect('inventory:po_list')


def edit_supplier(request, supplier_id):
    # Find the supplier or return a 404 error if it doesn't exist
    supplier = get_object_or_404(Supplier, id=supplier_id)
    
    if request.method == 'POST':
        # Update the fields with the new data from the form
        supplier.name = request.POST.get('name')
        supplier.contact_name = request.POST.get('contact_name')
        supplier.phone = request.POST.get('phone')
        supplier.email = request.POST.get('email')
        supplier.address = request.POST.get('address')
        
        supplier.save()
        messages.success(request, f"Supplier '{supplier.name}' updated successfully!")
        return redirect('inventory:supplier_list')
        
    # If it's a GET request, just show the page with the current data
    return render(request, 'inventory/edit_supplier.html', {
        'supplier': supplier
    })

def delete_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Soft Delete: Just mark them as inactive instead of wiping the data!
        supplier.is_active = False
        supplier.save()
        
        messages.success(request, f"Supplier '{supplier.name}' has been archived and hidden from the system.")
            
    return redirect('inventory:supplier_list')

def unarchive_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        
        # Restore the supplier!
        supplier.is_active = True
        supplier.save()
        
        messages.success(request, f"Supplier '{supplier.name}' has been restored and is active again.")
            
    return redirect('inventory:supplier_list')