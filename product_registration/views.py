from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.contrib import messages # 1. IMPORT MESSAGES
from django.http import JsonResponse
from inventory.models import InventoryItem, Category, Supplier

def create_product(request, pk=None):
    item = None
    if pk:
        item = get_object_or_404(InventoryItem, pk=pk)

    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        item_name = request.POST.get('item_name')
        category_id = request.POST.get('category')
        supplier_id = request.POST.get('supplier')
        quantity = request.POST.get('quantity', 0)
        barcode_id = request.POST.get('barcode_id')
        price = request.POST.get('price', 0)
        unit_cost = request.POST.get('unit_cost', 0)
        annual_demand = request.POST.get('annual_demand', 0)
        
        average_daily_sales = float(request.POST.get('average_daily_sales') or 0)
        max_daily_sales = float(request.POST.get('max_daily_sales') or 0)
        average_lead_time_days = int(request.POST.get('average_lead_time_days') or 0)
        max_lead_time_days = int(request.POST.get('max_lead_time_days') or 0)

        category = get_object_or_404(Category, id=category_id)
        supplier = Supplier.objects.filter(id=supplier_id).first()

        # 2. ADD THE DUPLICATE BARCODE CHECKS HERE
        if item:
            # If editing, ensure the barcode doesn't belong to a DIFFERENT item
            if InventoryItem.objects.filter(barcode_id=barcode_id).exclude(pk=item.pk).exists():
                messages.error(request, f"Update failed: Barcode '{barcode_id}' is already used by another product.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))
            
            # --- UPDATE LOGIC ---
            item.item_name = item_name
            item.category = category
            item.supplier = supplier
            item.quantity = quantity
            item.barcode_id = barcode_id
            item.price = price
            item.unit_cost = unit_cost
            item.annual_demand = annual_demand
            item.average_daily_sales = average_daily_sales
            item.max_daily_sales = max_daily_sales
            item.average_lead_time_days = average_lead_time_days
            item.max_lead_time_days = max_lead_time_days
            
            item.save() 
            messages.success(request, f"Product '{item.item_name}' updated successfully.")
            
        else:
            # If creating, ensure the barcode doesn't exist AT ALL
            if InventoryItem.objects.filter(barcode_id=barcode_id).exists():
                messages.error(request, f"Cannot add product: Barcode '{barcode_id}' is already registered to an existing item.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))

            # --- CREATE LOGIC ---
            InventoryItem.objects.create(
                item_name=item_name,
                category=category,
                supplier=supplier,
                quantity=quantity,
                barcode_id=barcode_id,
                price=price,
                unit_cost=unit_cost,
                annual_demand=annual_demand,
                average_daily_sales=average_daily_sales,
                max_daily_sales=max_daily_sales,
                average_lead_time_days=average_lead_time_days,
                max_lead_time_days=max_lead_time_days
            ) 
            messages.success(request, f"Product '{item_name}' added successfully.")
        
        return redirect('inventory:inventory_list')

    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })

@csrf_exempt
def add_category_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_cat = Category.objects.create(
                name=data.get('name'), 
                prefix=data.get('prefix').upper()
            )
            return JsonResponse({'status': 'success', 'id': new_cat.id, 'name': new_cat.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

@csrf_exempt
def add_supplier_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            new_sup = Supplier.objects.create(
                name=data.get('name'), 
                supplier_id=data.get('supplier_id') 
            )
            return JsonResponse({'status': 'success', 'id': new_sup.id, 'name': new_sup.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        

def get_categories_ajax(request):
    categories = list(Category.objects.values('id', 'name'))
    return JsonResponse(categories, safe=False)