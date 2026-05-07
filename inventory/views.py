from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from .models import InventoryItem, Category, Supplier
from decimal import Decimal

def inventory_list(request):
    """Displays all items in the inventory with their ABC status."""
    items = InventoryItem.objects.all().order_by('-id')
    return render(request, 'inventory/product_list.html', {'items': items})

def run_abc_analysis(request):
    items = InventoryItem.objects.all()
    
    # --- STEP 1: PRE-CALCULATION LOGIC ---
    # We create a list of tuples: (item_object, effective_value)
    # This avoids recalculating the math multiple times
    item_value_pairs = []
    total_store_value = Decimal('0')

    for item in items:
        # 1. Determine Effective Demand
        # Logic: If system has real sales data, use it. Otherwise, use manual estimate.
        # For now, we assume item.actual_sales_count exists in your model.
        actual_sales = getattr(item, 'actual_sales_count', 0)
        manual_est = int(item.annual_demand or 0)
        
        effective_demand = actual_sales if actual_sales > 0 else manual_est
        
        # 2. Calculate Value (Cost * Effective Demand)
        unit_cost = Decimal(str(item.unit_cost or 0))
        item_value = unit_cost * effective_demand
        
        item_value_pairs.append((item, item_value))
        total_store_value += item_value

    if total_store_value == 0:
        return redirect('inventory:inventory_list')

    # --- STEP 2: SORTING & CLASSIFICATION ---
    # Sort the pairs by the calculated value (Index 1) in descending order
    item_value_pairs.sort(key=lambda x: x[1], reverse=True)

    running_sum = Decimal('0')
    for item, item_value in item_value_pairs:
        running_sum += item_value
        cumulative_percentage = (running_sum / total_store_value) * 100

        # Assign Priority based on cumulative contribution to total value
        if cumulative_percentage <= 70:
            item.abc_classification = 'A'
        elif cumulative_percentage <= 90:
            item.abc_classification = 'B'
        else:
            item.abc_classification = 'C'
        
        item.save()

    return redirect('inventory:inventory_list')

def edit_product(request, pk):
    # 1. Fetch the existing item
    item = get_object_or_404(InventoryItem, pk=pk)
    
    if request.method == 'POST':
        # 2. Update the item with new data from the form
        item.item_name = request.POST.get('item_name')
        item.category_id = request.POST.get('category')
        item.supplier_id = request.POST.get('supplier')
        item.quantity = request.POST.get('quantity')
        item.barcode_id = request.POST.get('barcode_id')
        item.price = request.POST.get('price')
        item.unit_cost = request.POST.get('unit_cost', 0)
        item.annual_demand = request.POST.get('annual_demand', 0)
        
        # 3. Save the changes to the existing record (no duplicates!)
        item.save()
        return redirect('inventory:inventory_list')

    # 4. Show the form with the item data loaded
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()
    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })


# DELETE VIEW
def delete_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if request.method == 'POST':
        item.delete()
    return redirect('inventory:inventory_list')
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request'}, status=400)

def low_stock_view(request):
    """Specifically filters items that are at or below min_stock."""
    # This uses the property logic from your model
    low_stock_items = [item for item in InventoryItem.objects.all() if item.is_low_stock]
    return render(request, 'inventory/low_stock.html', {'items': low_stock_items})