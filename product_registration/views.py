from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
import json
from django.http import JsonResponse
from inventory.models import InventoryItem, Category, Supplier

def create_product(request, pk=None):
    # 1. If 'pk' is provided, we are EDITING. If not, we are CREATING.
    item = None
    if pk:
        item = get_object_or_404(InventoryItem, pk=pk)

    categories = Category.objects.all()
    suppliers = Supplier.objects.all()

    if request.method == 'POST':
        # Get common data
        item_name = request.POST.get('item_name')
        category_id = request.POST.get('category')
        supplier_id = request.POST.get('supplier')
        quantity = request.POST.get('quantity', 0)
        barcode_id = request.POST.get('barcode_id')
        price = request.POST.get('price', 0)
        unit_cost = request.POST.get('unit_cost', 0)
        annual_demand = request.POST.get('annual_demand', 0)

        category = get_object_or_404(Category, id=category_id)
        supplier = Supplier.objects.filter(id=supplier_id).first()

        if item:
            # --- UPDATE LOGIC ---
            item.item_name = item_name
            item.category = category
            item.supplier = supplier
            item.quantity = quantity
            item.barcode_id = barcode_id
            item.price = price
            item.unit_cost = unit_cost
            item.annual_demand = annual_demand
            item.save() # This updates the existing row
        else:
            # --- CREATE LOGIC ---
            InventoryItem.objects.create(
                item_name=item_name,
                category=category,
                supplier=supplier,
                quantity=quantity,
                barcode_id=barcode_id,
                price=price,
                unit_cost=unit_cost,
                annual_demand=annual_demand
            )
        
        return redirect('inventory:inventory_list')

    return render(request, 'product_registration/create_product.html', {
        'item': item, # Passes existing item to the form
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