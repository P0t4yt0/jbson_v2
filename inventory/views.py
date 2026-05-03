from django.shortcuts import render, redirect, get_object_or_404
from .models import InventoryItem, Category, Supplier

def inventory_list(request):
    """Displays all items in the inventory with their ABC status."""
    items = InventoryItem.objects.all()
    return render(request, 'inventory/product_list.html', {'items': items})

def create_product(request):
    """Handles the creation of new hardware products."""
    categories = Category.objects.all()
    suppliers = Supplier.objects.all()
    
    if request.method == 'POST':
        # Logic to save the product will go here
        pass
        
    return render(request, 'inventory/create_product.html', {
        'categories': categories,
        'suppliers': suppliers
    })

def low_stock_view(request):
    """Specifically filters items that are at or below min_stock."""
    # This uses the property logic from your model
    low_stock_items = [item for item in InventoryItem.objects.all() if item.is_low_stock]
    return render(request, 'inventory/low_stock.html', {'items': low_stock_items})