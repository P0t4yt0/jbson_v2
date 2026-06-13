import json
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from inventory.models import InventoryItem, Category, Supplier, GeneratedBarcode, ProductBatch

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

        if not category_id:
            messages.error(request, "Error: Please select a valid Category.")
            return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))
            
        category = get_object_or_404(Category, id=category_id)
        
        supplier = None
        if supplier_id:
            supplier = Supplier.objects.filter(id=supplier_id).first()

        if item:
            # UNIQUE CHECK FOR UPDATING: Exclude current item
            if InventoryItem.objects.filter(barcode_id=barcode_id).exclude(pk=item.pk).exists():
                messages.error(request, f"Update failed: Barcode '{barcode_id}' is already used by another product.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))
            
            if InventoryItem.objects.filter(item_name__iexact=item_name).exclude(pk=item.pk).exists():
                messages.error(request, f"Update failed: Product name '{item_name}' already exists.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))
            
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

            # I-SAVE SA BARCODE HISTORY
            today_str = timezone.now().strftime('%Y%m%d')
            manual_batch_id = f"MA{today_str}"
            
            GeneratedBarcode.objects.get_or_create(
                barcode_id=barcode_id,
                defaults={
                    'product_name': item_name,
                    'batch_id': manual_batch_id
                }
            )

            messages.success(request, f"Product '{item.item_name}' updated successfully.")
            
        else:
            # UNIQUE CHECK FOR CREATING NEW ITEM
            if InventoryItem.objects.filter(barcode_id=barcode_id).exists():
                messages.error(request, f"Cannot add product: Barcode '{barcode_id}' is already registered to an existing item.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))

            if InventoryItem.objects.filter(item_name__iexact=item_name).exists():
                messages.error(request, f"Cannot add product: Product name '{item_name}' already exists.")
                return redirect(request.META.get('HTTP_REFERER', 'inventory:inventory_list'))

            # BULLETPROOF ID GENERATOR: Force clean prefix and find max number
            if category and category.prefix:
                prefix = category.prefix.replace(" ", "").strip().upper()
            else:
                safe_name = category.name.replace(" ", "").strip()
                prefix = safe_name[:3].upper().ljust(3, 'X')

            existing_items = InventoryItem.objects.filter(product_id__icontains=prefix)
            max_num = 0
            for ext_item in existing_items:
                numeric_matches = re.findall(r'\d+', ext_item.product_id)
                if numeric_matches:
                    num = int(numeric_matches[-1])
                    if num > max_num:
                        max_num = num
            
            new_product_id = f"{prefix}{str(max_num + 1).zfill(3)}"
            
            # STRICT FALLBACK: Verify the generated ID doesn't exist just to be 100% sure
            while InventoryItem.objects.filter(product_id=new_product_id).exists():
                max_num += 1
                new_product_id = f"{prefix}{str(max_num + 1).zfill(3)}"

            new_item = InventoryItem.objects.create(
                product_id=new_product_id, 
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

            qty_int = int(quantity) if quantity else 0
            exp_date = request.POST.get('expiry_date') 
            
            ProductBatch.objects.create(
                product=new_item,
                quantity_received=qty_int,
                quantity_on_hand=qty_int,
                expiry_date=exp_date if exp_date else None,
                status='active'
            )

            today_str = timezone.now().strftime('%Y%m%d')
            manual_batch_id = f"MA{today_str}"
            
            existing_history = GeneratedBarcode.objects.filter(product_name__iexact=item_name).first()
            if existing_history:
                existing_history.barcode_id = barcode_id
                existing_history.save()
            else:
                GeneratedBarcode.objects.create(
                    barcode_id=barcode_id,
                    product_name=item_name,
                    batch_id=manual_batch_id
                )

            messages.success(request, f"Product '{item_name}' added successfully.")
        
        return redirect('inventory:inventory_list')

    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })

def add_category_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            cat_name = data.get('name', '').strip()
            cat_prefix = data.get('prefix', '').strip().upper()

            if Category.objects.filter(name__iexact=cat_name).exists():
                return JsonResponse({'status': 'error', 'message': f"Category '{cat_name}' already exists!"}, status=400)

            new_cat = Category.objects.create(
                name=cat_name, 
                prefix=cat_prefix
            )
            return JsonResponse({'status': 'success', 'id': new_cat.id, 'name': new_cat.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': "An unexpected error occurred."}, status=400)

def add_supplier_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            sup_name = data.get('name', '').strip()
            sup_id = data.get('supplier_id', '').strip()

            if Supplier.objects.filter(name__iexact=sup_name).exists():
                return JsonResponse({'status': 'error', 'message': f"Supplier '{sup_name}' already exists!"}, status=400)

            new_sup = Supplier.objects.create(
                name=sup_name, 
                supplier_id=sup_id 
            )
            return JsonResponse({'status': 'success', 'id': new_sup.id, 'name': new_sup.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': "An unexpected error occurred."}, status=400)

def get_categories_ajax(request):
    categories = list(Category.objects.values('id', 'name'))
    return JsonResponse(categories, safe=False)

def check_barcode_history_ajax(request):
    product_name = request.GET.get('product_name', '').strip()
    if product_name:
        record = GeneratedBarcode.objects.filter(product_name__iexact=product_name).first()
        if record:
            return JsonResponse({'status': 'found', 'barcode_id': record.barcode_id})
    return JsonResponse({'status': 'not_found'})