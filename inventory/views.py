from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from django.db.models import Q, F, ProtectedError
from django.contrib import messages # IDINAGDAG NATIN ITO PARA SA NOTIFICATIONS
from .models import InventoryItem, Category, Supplier
from decimal import Decimal

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
    suppliers = Supplier.objects.all()
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