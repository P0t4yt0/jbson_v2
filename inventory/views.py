from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from .models import InventoryItem, Category, Supplier

def inventory_list(request):
    """Displays all items in the inventory with their ABC status."""
    items = InventoryItem.objects.all().order_by('-id')
    return render(request, 'inventory/product_list.html', {'items': items})

def create_product(request):
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        # Get data from the POST request
        item_name = request.POST.get('item_name')
        product_id = request.POST.get('product_id')
        category_id = request.POST.get('category')
        quantity = request.POST.get('quantity')
        barcode_id = request.POST.get('barcode_id')
        price = request.POST.get('price')

        # Create and Save the product object
        category = Category.objects.get(id=category_id)
        InventoryItem.objects.create(
            item_name=item_name,
            product_id=product_id,
            category=category,
            quantity=quantity,
            barcode_id=barcode_id,
            price=price
        )
        return redirect('inventory:inventory_list')

    return render(request, 'inventory/create_product.html', {
        'categories': categories,
        'suppliers': suppliers
    })

@csrf_exempt
def add_category_ajax(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name')
            prefix = data.get('prefix')

            if name and prefix:
                # This line creates the record in your database
                new_cat = Category.objects.create(
                    name=name, 
                    prefix=prefix.upper()
                )
                return JsonResponse({
                    'status': 'success',
                    'id': new_cat.id,
                    'name': new_cat.name
                })
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        
def edit_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    
    if request.method == 'POST':
        # ... your save logic here ...
        return redirect('inventory:product_list')

    categories = Category.objects.all()
    suppliers = Supplier.objects.all()
    
    # We point this to 'create_product.html' so you don't have to maintain two files!
    return render(request, 'inventory/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })

@csrf_exempt
def add_supplier_ajax(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        name = data.get('name')
        sup_id = data.get('supplier_id') # This is the random "SUP-XXXX"

        try:
            # IMPORTANT: Make sure the names on the left match your models.py
            new_sup = Supplier.objects.create(
                name=name, 
                # If your model doesn't have supplier_id, comment the line below out:
                supplier_id=sup_id 
            )
            return JsonResponse({'status': 'success', 'id': new_sup.id, 'name': new_sup.name})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

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