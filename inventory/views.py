from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from django.db.models import Q, F
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
        item.item_name = request.POST.get('item_name')
        item.category_id = request.POST.get('category')
        item.supplier_id = request.POST.get('supplier')
        item.quantity = request.POST.get('quantity')
        item.barcode_id = request.POST.get('barcode_id')
        item.price = request.POST.get('price')
        item.unit_cost = request.POST.get('unit_cost', 0)
        item.annual_demand = request.POST.get('annual_demand', 0)
        
        item.save()
        return redirect('inventory:inventory_list')

    categories = Category.objects.all()
    suppliers = Supplier.objects.all()
    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })

# SINGLE DELETE VIEW (Inayos nang konti para tumugma sa bagong HTML)
def delete_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    item.delete()
    messages.success(request, f'Product "{item.item_name}" deleted successfully.')
    return redirect('inventory:inventory_list')

# --- BAGONG BULK DELETE VIEW ---
def bulk_delete_products(request):
    if request.method == 'POST':
        ids_string = request.POST.get('product_ids', '')
        if ids_string:
            id_list = ids_string.split(',')
            deleted_count, _ = InventoryItem.objects.filter(pk__in=id_list).delete()
            messages.success(request, f'Successfully deleted {deleted_count} product(s).')
    return redirect('inventory:inventory_list')

def low_stock_view(request):
    """Specifically filters items that are at or below min_stock."""
    low_stock_items = [item for item in InventoryItem.objects.all() if item.is_low_stock]
    return render(request, 'inventory/low_stock.html', {'items': low_stock_items})