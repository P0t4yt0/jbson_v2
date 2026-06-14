import csv
import json
import random
import re
from datetime import timedelta
from decimal import Decimal
import barcode
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, DecimalField, F, ProtectedError, Q, Sum, Prefetch
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from activity_log.utils import log_system_activity
from billing_payment.models import Invoice, SalesReturn
from point_of_sale.models import Transaction, TransactionItem
from reports_analytics.models import Expense
from security.models import EmployeeProfile
from .models import Category, GeneratedBarcode, InventoryItem, PurchaseOrder, PurchaseOrderItem, Supplier, ProductBatch
from django.views.decorators.http import require_POST

def generate_unique_barcode():
    while True:
        base_number = f"480{random.randint(100000000, 999999999)}"
        EAN_class = barcode.get_barcode_class('ean13')
        full_barcode = EAN_class(base_number).get_fullcode()
        
        if not GeneratedBarcode.objects.filter(barcode_id=full_barcode).exists() and \
           not InventoryItem.objects.filter(barcode_id=full_barcode).exists():
            return full_barcode

def is_admin_check(user):
    return user.is_authenticated and getattr(user, "role", "employee") == "admin"

@login_required        
def inventory_list(request):
    search_query = request.GET.get('search', '').strip()
    category_id = request.GET.get('category', '')
    low_stock = request.GET.get('low_stock', '')
    priority = request.GET.get('priority', '')
    sort_query = request.GET.get('sort', '')
    supplier_id = request.GET.get('supplier', '')
    per_page = request.GET.get('per_page', 10) 

    active_batches_prefetch = Prefetch(
        'batches',
        queryset=ProductBatch.objects.filter(quantity_on_hand__gt=0).order_by('date_received')
    )

    items = InventoryItem.objects.prefetch_related(active_batches_prefetch).all()

    if search_query:
        items = items.filter(
            Q(item_name__icontains=search_query) |
            Q(barcode_id__icontains=search_query) |
            Q(supplier__name__icontains=search_query) |
            Q(product_id__icontains=search_query) 
        )

    if category_id:
        items = items.filter(category_id=category_id)

    if priority:
        items = items.filter(abc_classification=priority)

    if low_stock == 'on':
        items = items.filter(quantity__lte=F('reorder_point'))

    if supplier_id:
        items = items.filter(supplier_id=supplier_id)

    if sort_query == 'supplier':
        items = items.order_by('supplier__name', 'abc_classification', '-id')
    elif sort_query == '-supplier':
        items = items.order_by('-supplier__name', 'abc_classification', '-id')
    else:
        items = items.order_by('abc_classification', '-id')

    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(items, per_page)
    page_number = request.GET.get('page', 1)
    items_page = paginator.get_page(page_number)

    today = timezone.now().date()
    time_window = today + timedelta(days=30) 

    expiring_batches = ProductBatch.objects.filter(
        expiry_date__isnull=False,       
        expiry_date__gte=today,          
        expiry_date__lte=time_window,    
        quantity_on_hand__gt=0           
    ).order_by('expiry_date')[:6]

    context = {
        'items': items_page, 
        'categories': Category.objects.all(),
        'suppliers': Supplier.objects.filter(is_active=True).order_by('name'),
        'search_query': search_query,
        'selected_category': category_id,
        'low_stock': low_stock,
        'selected_priority': priority,
        'current_sort': sort_query,
        'selected_supplier': supplier_id,
        'per_page': per_page,
        'expiring_batches': expiring_batches,
    }
    return render(request, 'inventory/product_list.html', context)

@login_required
def edit_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)

    if not request.user.is_superuser and not request.user.profile.can_edit_product:
        messages.error(request, "You do not have authorization to edit this product.")
        return redirect('inventory:inventory_list') # O kung ano man ang pangalan ng inventory page mo
    
    if request.method == 'POST':
        item.item_name = request.POST.get('item_name') or item.item_name
        item.category_id = request.POST.get('category') or item.category_id
        item.supplier_id = request.POST.get('supplier') or item.supplier_id
        item.quantity = request.POST.get('quantity') or item.quantity
        item.barcode_id = request.POST.get('barcode_id') or item.barcode_id
        item.price = request.POST.get('price') or item.price
        item.unit_cost = request.POST.get('unit_cost') or item.unit_cost
        item.annual_demand = request.POST.get('annual_demand') or item.annual_demand
        
        item.average_daily_sales = float(request.POST.get('average_daily_sales') or item.average_daily_sales or 0)
        item.max_daily_sales = float(request.POST.get('max_daily_sales') or item.max_daily_sales or 0)
        item.average_lead_time_days = int(request.POST.get('average_lead_time_days') or item.average_lead_time_days or 0)
        item.max_lead_time_days = int(request.POST.get('max_lead_time_days') or item.max_lead_time_days or 0)

        item.save()
        log_system_activity(
            user=request.user,
            action="EDIT PRODUCT",
            description=f"Updated details/ROP for product: {item.item_name}"
        )
        return redirect('inventory:inventory_list')

    categories = Category.objects.all()
    suppliers = Supplier.objects.filter(is_active=True)
    return render(request, 'product_registration/create_product.html', {
        'item': item,
        'categories': categories,
        'suppliers': suppliers
    })

@login_required
def delete_product(request, pk):
    item = get_object_or_404(InventoryItem, pk=pk)
    if not request.user.is_superuser and not request.user.employeeprofile.can_delete_product:
        messages.error(request, "You do not have authorization to delete this product.")
        return redirect('inventory:inventory_list')
    try:
        item_name = item.item_name
        item.delete()
        log_system_activity(
            user=request.user,
            action="DELETE PRODUCT",
            description=f"Deleted inventory item: '{item_name}'"
        )
        messages.success(request, f'Product "{item_name}" deleted successfully.')
    except ProtectedError:
        messages.error(request, f'Cannot delete "{item.item_name}" because it is already linked to existing transactions/sales.')
      
    return redirect('inventory:inventory_list')

@login_required
def bulk_delete_products(request):

    if request.method == 'POST':
        ids_string = request.POST.get('product_ids', '')
        if ids_string:
            id_list = ids_string.split(',')
            try:
                deleted_count, _ = InventoryItem.objects.filter(pk__in=id_list).delete()
                log_system_activity(
                    user=request.user,
                    action="BULK DELETE",
                    description=f"Bulk deleted {deleted_count} inventory items."
                )
                messages.success(request, f'Successfully deleted {deleted_count} product(s).')
            except ProtectedError:
                messages.error(request, 'Action failed. Some of the selected products cannot be deleted because they have existing transaction records.')
                
    return redirect('inventory:inventory_list')

@login_required
def preview_csv_import(request):
    if not request.user.is_superuser and not request.user.profile.can_import_csv:
        messages.error(request, "You do not have the authorization to import csv.")
        return redirect('inventory:inventory_list')
    
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        if not csv_file or not csv_file.name.endswith('.csv'):
            return JsonResponse({'status': 'error', 'message': 'Invalid file. Please upload a CSV file.'})

        try:
            file_data = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(file_data)
            
            preview_data = []
            category_counters = {}
            
            for row in reader:
                cat_name = row.get('CATEGORY', '').strip()
                category = Category.objects.filter(name__iexact=cat_name).first()
                
                prefix = category.prefix.strip().upper() if category and category.prefix else cat_name[:3].upper().ljust(3, 'X')
                
                if prefix not in category_counters:
                    existing_items = InventoryItem.objects.filter(product_id__startswith=prefix)
                    max_num = 0
                    for item in existing_items:
                        numeric_matches = re.findall(r'\d+', item.product_id)
                        if numeric_matches:
                            num = int(numeric_matches[-1])
                            if num > max_num:
                                max_num = num
                    category_counters[prefix] = max_num
                
                category_counters[prefix] += 1
                new_product_id = f"{prefix}{str(category_counters[prefix]).zfill(3)}"
                
                barcode_id = row.get('BARCODE', '').strip()
                is_auto_generated = False
                if not barcode_id:
                    barcode_id = generate_unique_barcode()
                    is_auto_generated = True

                preview_data.append({
                    'product_id': new_product_id,
                    'item_name': row.get('PRODUCT_NAME', ''),
                    'supplier': row.get('SUPPLIER', ''),
                    'category': cat_name,
                    'price': row.get('PRICE', 0),
                    'quantity': row.get('QTY', 0),
                    'barcode_id': barcode_id,
                    'is_auto_generated': is_auto_generated
                })

            return JsonResponse({'status': 'success', 'data': preview_data})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
            
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'})

@login_required
def confirm_csv_import(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            rows = data.get('rows', [])
            
            today_str = timezone.now().strftime('%Y%m%d')
            last_batch = GeneratedBarcode.objects.filter(batch_id__startswith=f"AU{today_str}").order_by('-batch_id').first()
            seq = (int(last_batch.batch_id.split('-')[-1]) + 1) if last_batch and '-' in last_batch.batch_id else 1
            current_batch_id = f"AU{today_str}-{seq:02d}"
            
            generated_barcodes_to_create = []
            new_barcodes_count = 0
            
            for row in rows:
                current_barcode = row['barcode_id'].strip()
                duplicate_item = InventoryItem.objects.filter(barcode_id=current_barcode).first()
                
                if duplicate_item and duplicate_item.product_id != row['product_id']:
                    return JsonResponse({
                        'status': 'error', 
                        'message': f"The Barcode '{current_barcode}' is already used by item '{duplicate_item.item_name}' ({duplicate_item.product_id}). Please fix your CSV file."
                    })

                category, _ = Category.objects.get_or_create(
                    name=row['category'],
                    defaults={'prefix': row['category'][:3].upper()}
                )
                
                supplier_obj = None
                if row.get('supplier'):
                    supplier_obj, _ = Supplier.objects.get_or_create(name=row['supplier'])
                
                InventoryItem.objects.update_or_create(
                    product_id=row['product_id'],
                    defaults={
                        'item_name': row['item_name'],
                        'category': category,
                        'supplier': supplier_obj,
                        'price': row['price'],
                        'quantity': row['quantity'],
                        'barcode_id': current_barcode,
                    }
                )
                
                if row.get('is_auto_generated'):
                    generated_barcodes_to_create.append(
                        GeneratedBarcode(
                            barcode_id=current_barcode,
                            product_name=row['item_name'],
                            batch_id=current_batch_id
                        )
                    )
                    new_barcodes_count += 1
                    
            if generated_barcodes_to_create:
                GeneratedBarcode.objects.bulk_create(generated_barcodes_to_create)
                
            log_system_activity(
                user=request.user, 
                action="CSV IMPORT", 
                description=f"Imported {len(rows)} products. Auto-generated {new_barcodes_count} barcodes."
            )
            messages.success(request, f"Successfully imported {len(rows)} products!")
            
            return JsonResponse({
                'status': 'success',
                'batch_id': current_batch_id,
                'new_barcodes_count': new_barcodes_count,
                'redirect_url': '/inventory/'
            })
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({'status': 'error', 'message': 'Invalid method'})

@login_required
def run_abc_analysis(request):
    items = InventoryItem.objects.all()
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

@login_required
def low_stock_view(request):
    low_stock_items = [item for item in InventoryItem.objects.all() if item.is_low_stock]
    return render(request, 'inventory/low_stock.html', {'items': low_stock_items})

@login_required
def auto_calibrate_rop(request):
    days = int(request.GET.get('days', 7))
    days = max(7, min(days, 365))

    lookback = timezone.now() - timedelta(days=days)
    items = InventoryItem.objects.all()
    updated_count = 0

    for item in items:
        sales = TransactionItem.objects.filter(
            inventory_item=item,
            transaction__status__in=['completed', 'paid'],
            transaction__date_created__gte=lookback
        )

        daily_sales_dict = {}
        for sale in sales:
            date_str = sale.transaction.date_created.strftime('%Y-%m-%d')
            daily_sales_dict[date_str] = daily_sales_dict.get(date_str, 0) + sale.quantity

        if daily_sales_dict:
            total_sales = sum(daily_sales_dict.values())
            active_days = len(daily_sales_dict)

            item.average_daily_sales = float(total_sales) / float(active_days)
            item.max_daily_sales = float(max(daily_sales_dict.values()))
            item.save()
            updated_count += 1

    log_system_activity(
        user=request.user,
        action="AUTO CALIBRATE",
        description=f"Auto-calibrated ROP for {updated_count} items based on last {days} days of sales (blank days excluded)."
    )
    messages.success(request, f"Done! ROP updated for {updated_count} items. Blank days were excluded from the average so your numbers stay accurate.")
    return redirect('inventory:inventory_list')

@login_required
def category_list(request):
    if request.method == 'POST':
        if not request.user.is_superuser and not request.user.profile.can_add_category:
            messages.error(request, "You do not have authorization to add a category.")
            return redirect('inventory:category_list')
        
        new_name = request.POST.get('name')
        new_prefix = request.POST.get('prefix')
        
        if new_name and new_prefix:
            if not Category.objects.filter(name=new_name).exists():
                Category.objects.create(name=new_name, prefix=new_prefix)
                log_system_activity(
                    user=request.user,
                    action="ADD CATEGORY",
                    description=f"Created new category: '{new_name}'"
                )
                messages.success(request, f'Category "{new_name}" successfully added.')
            else:
                messages.error(request, f'Category "{new_name}" already exists.')
        else:
            messages.error(request, 'Error: Category name or prefix is missing.')
        
        return redirect('inventory:category_list')

    categories = Category.objects.prefetch_related('items').all()
    return render(request, 'inventory/category_list.html', {'categories': categories})

@login_required
def edit_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if not request.user.is_superuser and not request.user.profile.can_edit_category:
        messages.error(request, "You do not have authorization to edit this category.")
        return redirect('inventory:category_list')

    if request.method == 'POST':
        new_name = request.POST.get('name')
        if new_name:
            old_name = category.name
            category.name = new_name
            category.save()
            
            log_system_activity(
                user=request.user,
                action="EDIT CATEGORY",
                description=f"Renamed category from '{old_name}' to '{new_name}'"
            )
            messages.success(request, f'Category successfully renamed to "{new_name}".')
    return redirect('inventory:category_list')

@login_required
def delete_category(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if not request.user.is_superuser and not request.user.profile.can_delete_category:
        messages.error(request, "You do not have authorization to delete this category.")
        return redirect('inventory:category_list')

    try:
        cat_name = category.name
        category.delete()
        log_system_activity(
            user=request.user,
            action="DELETE CATEGORY",
            description=f"Deleted category: '{cat_name}'"
        )
        messages.success(request, f'Category "{cat_name}" deleted successfully.')
    except ProtectedError:
        messages.error(request, f'Cannot delete "{category.name}" because there are products currently assigned to it.')
        
    return redirect('inventory:category_list')

@login_required
def supplier_list(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        contact_name = request.POST.get('contact_name')
        phone = request.POST.get('phone')
        email = request.POST.get('email')
        address = request.POST.get('address')
        default_lt = request.POST.get('default_lead_time_days', 7)
        max_lt = request.POST.get('max_lead_time_days', 14)
        
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
            log_system_activity(
                user=request.user,
                action="ADD SUPPLIER",
                description=f"Added new supplier: '{name}'"
            )
            messages.success(request, f"Supplier '{name}' added successfully!")
            
        return redirect('inventory:supplier_list')

    search_query = request.GET.get('search', '').strip()
    per_page = request.GET.get('per_page', 10)

    suppliers = Supplier.objects.filter(is_active=True).order_by('name')
    
    if search_query:
        suppliers = suppliers.filter(
            Q(name__icontains=search_query) |
            Q(contact_name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(email__icontains=search_query)
        )
        
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(suppliers, per_page)
    page_number = request.GET.get('page', 1)
    suppliers_page = paginator.get_page(page_number)
    
    return render(request, 'inventory/supplier_list.html', {
        'suppliers': suppliers_page,
        'search_query': search_query,
        'per_page': per_page,
    })

@login_required
def edit_supplier(request, supplier_id):
    supplier = get_object_or_404(Supplier, id=supplier_id)
    
    if request.method == 'POST':
        supplier.save()
        
        for product in InventoryItem.objects.filter(supplier=supplier):
            product.save()

        log_system_activity(
            user=request.user,
            action="EDIT SUPPLIER",
            description=f"Updated details for supplier: '{supplier.name}'"
        )
        messages.success(request, f"Supplier '{supplier.name}' updated! All associated product reorder points have been instantly recalculated.")
        return redirect('inventory:supplier_list')
    
    return render(request, 'inventory/edit_supplier.html', {
        'supplier': supplier
    })

@login_required
def delete_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        supplier.is_active = False
        supplier.save()

        log_system_activity(
            user=request.user,
            action="ARCHIVE SUPPLIER",
            description=f"Archived supplier '{supplier.name}'"
        )
        messages.success(request, f"Supplier '{supplier.name}' has been archived and hidden from the system.")
            
    return redirect('inventory:supplier_list')

@login_required
def archived_supplier_list(request):
    search_query = request.GET.get('search', '').strip()
    per_page = request.GET.get('per_page', 10)

    suppliers = Supplier.objects.filter(is_active=False).order_by('name')
    
    if search_query:
        suppliers = suppliers.filter(
            Q(name__icontains=search_query) |
            Q(contact_name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(email__icontains=search_query)
        )
        
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10

    paginator = Paginator(suppliers, per_page)
    page_number = request.GET.get('page', 1)
    suppliers_page = paginator.get_page(page_number)
    
    return render(request, 'inventory/archived_supplier_list.html', {
        'suppliers': suppliers_page,
        'search_query': search_query,
        'per_page': per_page,
    })

@login_required
def unarchive_supplier(request, supplier_id):
    if request.method == 'POST':
        supplier = get_object_or_404(Supplier, id=supplier_id)
        supplier.is_active = True
        supplier.save()

        log_system_activity(
            user=request.user,
            action="RESTORE SUPPLIER",
            description=f"Restored archived supplier '{supplier.name}'"
        )
        messages.success(request, f"Supplier '{supplier.name}' has been restored.")
            
    return redirect('inventory:archived_supplier_list')

@login_required
def po_list(request):
    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')
    return render(request, 'inventory/po_list.html', {
        'purchase_orders': purchase_orders
    })

@login_required
def create_po(request):
    if request.method == 'POST':
        supplier_id = request.POST.get('supplier')
        expected_delivery = request.POST.get('expected_delivery')
        
        product_ids = request.POST.getlist('product_id[]')
        quantities = request.POST.getlist('quantity[]')
        unit_costs = request.POST.getlist('unit_cost[]')
        
        supplier = get_object_or_404(Supplier, id=supplier_id)
        fallback_date = timezone.now().date() + timezone.timedelta(days=7)
        action = request.POST.get('action')
        po_status = 'pending' if action == 'submit_po' else 'draft'
        
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            expected_delivery=expected_delivery if expected_delivery else fallback_date,
            status=po_status
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
            log_system_activity(user=request.user, action="DRAFT PO", description=f"Drafted PO for {supplier.name}.")
            messages.success(request, f"Draft saved successfully for {supplier.name}.")
            return redirect('inventory:edit_po', po_id=po.id) 
        else:
            log_system_activity(user=request.user, action="GENERATE PO", description=f"Generated PO {po.po_number} for {supplier.name}.")
            messages.success(request, f"Purchase Order {po.po_number} officially generated!")
            return redirect('inventory:create_po')

    suppliers = Supplier.objects.filter(is_active=True)
    products = InventoryItem.objects.all().order_by('item_name')
    
    auto_supplier_id = None
    auto_items = []
    fallback_date_str = (timezone.now().date() + timezone.timedelta(days=7)).strftime('%Y-%m-%d')

    low_stock_qs = InventoryItem.objects.exclude(supplier__isnull=True).annotate(
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

    suppliers_needing_restock = (
        low_stock_qs
        .values('supplier__id', 'supplier__name')
        .annotate(item_count=Count('id', distinct=True))
        .order_by('supplier__id')
        .distinct()
        .order_by('-item_count')
    )

    if request.GET.get('auto') == 'true':
        target_supplier_id = request.GET.get('supplier_id')

        if target_supplier_id:
            auto_supplier_id = int(target_supplier_id)
        else:
            top_supplier = suppliers_needing_restock.first()
            if top_supplier:
                auto_supplier_id = int(top_supplier['supplier__id'])

        if auto_supplier_id:
            existing_draft = PurchaseOrder.objects.filter(
                supplier_id=auto_supplier_id, status='draft'
            ).first()
            
            if existing_draft:
                return redirect('inventory:edit_po', po_id=existing_draft.id)
                
            items_for_supplier = low_stock_qs.filter(supplier_id=auto_supplier_id)

            for item in items_for_supplier:
                avg_sales = float(item.average_daily_sales or 0)
                safety_stock = getattr(item, 'safety_stock', 0)
                
                if avg_sales > 0:
                    target_stock_level = int(round(avg_sales * 30)) + safety_stock
                else:
                    target_stock_level = item.reorder_point * 2
                    
                recommended_qty = target_stock_level - item.effective_qty
                if recommended_qty <= 0: 
                    recommended_qty = max(item.reorder_point, 1)

                cost = float(item.unit_cost or 0)
                subtotal = recommended_qty * cost

                auto_items.append({
                    'id': item.id,
                    'name': item.item_name,
                    'qty': recommended_qty,
                    'cost': str(item.unit_cost),
                    'subtotal': f"{subtotal:.2f}"
                })

            supplier_obj = Supplier.objects.get(id=auto_supplier_id)
            messages.info(request, f"Draft auto-filled for {supplier_obj.name}. Items already pending delivery were ignored.")
        elif not target_supplier_id and not suppliers_needing_restock:
            messages.success(request, "Inventory is healthy or all low-stock items are already on their way!")

    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')

    return render(request, 'inventory/create_po.html', {
        'suppliers': suppliers,
        'products': products,
        'auto_supplier_id': auto_supplier_id,
        'auto_items': auto_items,
        'fallback_date_str': fallback_date_str,
        'purchase_orders': purchase_orders,
        'suppliers_needing_restock': suppliers_needing_restock
    })

@login_required
def edit_po(request, po_id):
    target_po = get_object_or_404(PurchaseOrder, id=po_id)
    
    if request.method == 'POST':
        if target_po.status == 'draft':
            supplier_id = request.POST.get('supplier')
            if supplier_id:
                target_po.supplier = get_object_or_404(Supplier, id=supplier_id)
                
            expected_delivery = request.POST.get('expected_delivery')
            if expected_delivery:
                target_po.expected_delivery = expected_delivery
            
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
                log_system_activity(user=request.user, action="SUBMIT DRAFT PO", description=f"Submitted Draft PO {target_po.po_number} as official.")
                messages.success(request, f"Order {target_po.po_number} has been officially submitted!")
                return redirect('inventory:create_po') 
            else:
                log_system_activity(user=request.user, action="EDIT DRAFT PO", description=f"Updated Draft PO {target_po.po_number}.")
                messages.success(request, f"Draft {target_po.po_number} successfully updated!")
                return redirect('inventory:edit_po', po_id=target_po.id)
        else:
            messages.error(request, "This order is already being processed and cannot be edited.")
        return redirect('inventory:edit_po', po_id=target_po.id)

    purchase_orders = PurchaseOrder.objects.all().order_by('-order_date')
    suppliers = Supplier.objects.filter(is_active=True)
    products = InventoryItem.objects.all().order_by('item_name')
    
    formatted_date = target_po.expected_delivery.strftime('%Y-%m-%d') if target_po.expected_delivery else ''

    low_stock_qs = InventoryItem.objects.exclude(supplier__isnull=True).annotate(
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

    suppliers_needing_restock = (
        low_stock_qs
        .values('supplier__id', 'supplier__name')
        .annotate(item_count=Count('id', distinct=True))
        .order_by('supplier__id')
        .distinct()
        .order_by('-item_count')
    )

    return render(request, 'inventory/create_po.html', {
        'purchase_orders': purchase_orders,
        'suppliers': suppliers,
        'products': products,
        'target_po': target_po,
        'edit_mode': True,
        'formatted_date': formatted_date,
        'suppliers_needing_restock': suppliers_needing_restock
    })

@login_required
@transaction.atomic
def receive_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    
    if po.status != 'pending':
        messages.error(request, "This order has already been processed or cancelled.")
        return redirect('inventory:create_po')
        
    for item in po.items.all():
        product = item.product
        
        current_qty = Decimal(product.quantity)
        ordered_qty = Decimal(item.quantity_ordered)
        
        current_total_value = current_qty * product.unit_cost
        new_delivery_value = ordered_qty * item.unit_cost
        
        new_total_quantity = current_qty + ordered_qty
        
        if new_total_quantity > 0:
            new_average_cost = (current_total_value + new_delivery_value) / new_total_quantity
            product.unit_cost = round(new_average_cost, 2)
            
        product.quantity += item.quantity_ordered
        product.save()
        
        item.quantity_received = item.quantity_ordered
        item.save()

        # --- BAGONG LOGIC PARA SA BATCH CREATION ---
        today_str = timezone.now().strftime('%y%m%d')
        batch_seq = ProductBatch.objects.filter(product=product, date_received=timezone.now().date()).count() + 1
        new_batch_code = f"BCH-{product.product_id}-{today_str}-{batch_seq:02d}"

        ProductBatch.objects.create(
            product=product,
            batch_code=new_batch_code,
            quantity_received=item.quantity_ordered,
            quantity_on_hand=item.quantity_ordered,
            date_received=timezone.now().date()
        )
        # -------------------------------------------
        
    po.status = 'received'
    po.save()

    log_system_activity(
        user=request.user,
        action="RECEIVE PO",
        description=f"Received delivery for PO {po.po_number}. Inventory stock, average costs, and FIFO batches updated."
    )
    messages.success(request, f"Delivery for {po.po_number} received! Inventory stock, costs, and FIFO queue have been safely updated.")
    return redirect('inventory:create_po')

@login_required
def delete_po(request, po_id):
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

@login_required
def print_po(request, po_id):
    po = get_object_or_404(PurchaseOrder, id=po_id)
    return render(request, 'inventory/print_po.html', {'po': po})

@login_required
def barcode_module_view(request):
    context = {}
    
    if request.method == 'POST':
        product_name = request.POST.get('product_name', '').strip()
        
        if product_name:
            in_history = GeneratedBarcode.objects.filter(product_name__iexact=product_name).exists()
            in_inventory = InventoryItem.objects.filter(item_name__iexact=product_name).exists()
            
            if in_history or in_inventory:
                messages.error(request, f"Cannot generate: The product '{product_name}' already exists in your Inventory or Barcode History.")
            else:
                full_barcode = generate_unique_barcode() 
                today_str = timezone.now().strftime('%Y%m%d')
                manual_batch_id = f"MA{today_str}"
                
                GeneratedBarcode.objects.create(
                    barcode_id=full_barcode,
                    product_name=product_name,
                    batch_id=manual_batch_id
                )
                
                log_system_activity(
                    user=request.user,
                    action="GENERATE BARCODE",
                    description=f"Generated new barcode ({full_barcode}) for '{product_name}'"
                )

                context['barcode_id'] = full_barcode
                context['product_name'] = product_name
                messages.success(request, f"Barcode generated successfully for '{product_name}'!")
        else:
            messages.error(request, "Product name is required to generate a barcode.")

    history_list = GeneratedBarcode.objects.all().order_by('-created_at')
    
    per_page = request.GET.get('per_page', 10)
    try:
        per_page = int(per_page)
    except ValueError:
        per_page = 10
        
    paginator = Paginator(history_list, per_page)
    page_number = request.GET.get('page', 1)
    history_page = paginator.get_page(page_number)
    
    context['history'] = history_page
    context['per_page'] = per_page

    return render(request, 'inventory/generate_barcode.html', context)

@login_required
def delete_generated_barcode(request, pk):
    if request.method == 'POST':
        barcode_record = get_object_or_404(GeneratedBarcode, pk=pk)
        product_name = barcode_record.product_name
        barcode_record.delete()
        
        log_system_activity(
            user=request.user,
            action="DELETE BARCODE",
            description=f"Deleted barcode history for '{product_name}'"
        )
        messages.success(request, f"Barcode history for '{product_name}' was successfully deleted.")        
    return redirect('inventory:generate_barcode_page')

@login_required
def fetch_barcode_batch(request, batch_id):
    barcodes = GeneratedBarcode.objects.filter(batch_id=batch_id).values('barcode_id', 'product_name')
    return JsonResponse({'status': 'success', 'barcodes': list(barcodes)})

@login_required
def admin_dashboard_view(request):
    if getattr(request.user, "role", "employee") != "admin":
        return redirect('employee_dashboard')
    
    today = timezone.now().date()

    expired_batches = ProductBatch.objects.filter(
        expiry_date__isnull=False,
        expiry_date__lte=today, 
        quantity_on_hand__gt=0
    )
    for batch in expired_batches:
        batch.quantity_on_hand = 0
        batch.status = 'pulled_out'
        batch.save()
        log_system_activity(
            user=request.user,
            action='AUTO PULL OUT',
            description=f"System automatically pulled out expired batch {batch.batch_code} ({batch.product.item_name})."
        )


    time_window = today + timedelta(days=30) 
    expiring_batches = ProductBatch.objects.filter(
        expiry_date__isnull=False,       
        expiry_date__gte=today,          
        expiry_date__lte=time_window,    
        quantity_on_hand__gt=0           
    ).order_by('expiry_date')[:6]

    date_filter = request.GET.get('filter', 'all_time')
    if date_filter == 'today': start_date = today
    elif date_filter == 'this_week': start_date = today - timedelta(days=today.weekday())
    elif date_filter == 'this_month': start_date = today.replace(day=1)
    elif date_filter == 'this_year': start_date = today.replace(month=1, day=1)
    else: start_date = None 

    tx_base = Transaction.objects.filter(status__in=['completed', 'paid'])
    po_base = PurchaseOrder.objects.filter(status='received')
    expense_base = Expense.objects.all()

    if start_date:
        tx_base = tx_base.filter(date_created__date__gte=start_date)
        po_base = po_base.filter(order_date__gte=start_date)
        if expense_base is not None: expense_base = expense_base.filter(expense_date__gte=start_date)

    total_sales = tx_base.aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
    total_purchase = po_base.aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
    sales_return = SalesReturn.objects.aggregate(t=Coalesce(Sum('total_refund'), Decimal('0.00'), output_field=DecimalField()))['t']
    invoice_due = Invoice.objects.filter(status='unpaid').aggregate(t=Coalesce(Sum('balance_due'), Decimal('0.00'), output_field=DecimalField()))['t']
    
    expenses = Decimal('0.00')
    if expense_base is not None:
        expenses = expense_base.aggregate(t=Coalesce(Sum('amount'), Decimal('0.00'), output_field=DecimalField()))['t']

    total_outflow = total_purchase + expenses
    net_profit = total_sales - total_outflow - sales_return

    chart_labels = []
    chart_sales_data = []
    chart_outflow_data = []
    chart_profit_data = []

    for i in range(6, -1, -1):
        current_day = today - timedelta(days=i)
        next_day = current_day + timedelta(days=1)
        
        chart_labels.append(current_day.strftime('%b %d'))
        
        d_sales = Transaction.objects.filter(
            date_created__gte=current_day,
            date_created__lt=next_day,
            status__in=['completed', 'credit']
        ).aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
        
        d_purchases = PurchaseOrder.objects.filter(
            status='received', 
            order_date__gte=current_day,
            order_date__lt=next_day
        ).aggregate(t=Coalesce(Sum('total_amount'), Decimal('0.00'), output_field=DecimalField()))['t']
        
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

    top_items_base = TransactionItem.objects.filter(transaction__status__in=['completed', 'credit'])
    if start_date:
        top_items_base = top_items_base.filter(transaction__date_created__gte=start_date)

    top_products_qs = top_items_base.values('inventory_item__item_name').annotate(total_sold=Sum('quantity')).order_by('-total_sold')[:5]
    
    donut_labels = [p['inventory_item__item_name'] for p in top_products_qs]
    donut_data = [float(p['total_sold']) for p in top_products_qs]

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
        'expiring_batches': expiring_batches,
    }

    return render(request, 'dashboard/dashboard.html', context)

@login_required
def employee_dashboard_view(request):
    if getattr(request.user, "role", "employee") == "admin":
        return redirect('admin_dashboard')

    today = timezone.now().date()
    
    date_filter = request.GET.get('filter', 'all_time')
    if date_filter == 'today': start_date = today
    elif date_filter == 'this_week': start_date = today - timedelta(days=today.weekday())
    elif date_filter == 'this_month': start_date = today.replace(day=1)
    elif date_filter == 'this_year': start_date = today.replace(month=1, day=1)
    else: start_date = None 

    todays_transactions = Transaction.objects.filter(date_created__date=today).count()
    total_active_products = InventoryItem.objects.count()
    pending_deliveries = PurchaseOrder.objects.filter(status='pending').count()
    
    low_stock_qs = InventoryItem.objects.filter(quantity__lte=F('reorder_point')).order_by('quantity')
    low_stock_count = low_stock_qs.count()
    low_stock_items = low_stock_qs[:5]

    top_items_base = TransactionItem.objects.filter(transaction__status__in=['completed', 'credit'])
    if start_date:
        top_items_base = top_items_base.filter(transaction__date_created__gte=start_date)

    top_products_qs = top_items_base.values('inventory_item__item_name').annotate(total_sold=Sum('quantity')).order_by('-total_sold')[:5]
    
    donut_labels = [p['inventory_item__item_name'] for p in top_products_qs]
    donut_data = [float(p['total_sold']) for p in top_products_qs]

    metrics = {
        'low_stock_count': low_stock_count,
        'todays_transactions': todays_transactions,
        'total_active_products': total_active_products,
        'pending_deliveries': pending_deliveries,
        'current_filter': date_filter,
    }

    context = {
        'metrics': metrics,
        'low_stock_items': low_stock_items,
        'top_products': top_products_qs,
        'donut_labels': json.dumps(donut_labels),
        'donut_data': json.dumps(donut_data),
    }

    return render(request, 'dashboard/employee_dashboard.html', context)

@login_required
def delete_user(request, user_id):
    if not request.user.is_superuser:
        messages.error(request, "Access denied.")
        return redirect('security:register')

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
        
    return redirect('security:register')

@login_required
@require_POST
def update_batch_dates(request, batch_id):
    try:
        data = json.loads(request.body)
        batch = ProductBatch.objects.get(id=batch_id)
        
        mfg = data.get('mfg_date')
        exp = data.get('expiry_date')
        
        batch.manufacturing_date = mfg if mfg else None
        batch.expiry_date = exp if exp else None
        batch.save()
        
        log_system_activity(
            user=request.user,
            action="UPDATE BATCH",
            description=f"Updated dates for batch {batch.batch_code} ({batch.product.item_name})"
        )
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@login_required
@require_POST
def pull_out_batch(request, batch_id):
    try:
        data = json.loads(request.body)
        reason = data.get('reason', 'Pulled Out')
        
        batch = ProductBatch.objects.get(id=batch_id)
        old_qty = batch.quantity_on_hand
        
        batch.quantity_on_hand = 0
        batch.status = 'pulled_out'
        batch.save() 
        
        log_system_activity(
            user=request.user,
            action="PULL OUT BATCH",
            description=f"Pulled out {old_qty} items from Batch {batch.batch_code} ({batch.product.item_name}). Reason: {reason}"
        )
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})