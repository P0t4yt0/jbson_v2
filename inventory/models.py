import re
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
from auditlog.registry import auditlog

# --- CATEGORY MODEL ---
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    prefix = models.CharField(max_length=5, unique=True, help_text="2-5 letter code for IDs")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'categories'
        ordering = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        # Ito ang kukunin ng auditlog para sa 'object_repr'
        return self.name
# --- SUPPLIER MODEL ---
class Supplier(models.Model):
    supplier_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)
    contact_name = models.CharField(max_length=100, blank=True)
    phone        = models.CharField(max_length=20, blank=True)
    email        = models.EmailField(blank=True)
    address      = models.TextField(blank=True)
    is_active    = models.BooleanField(default=True) # <-- ADD THIS LINE
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']

    def __str__(self):
        return self.name

# --- INVENTORY ITEM MODEL (Core of ABC Analysis) ---
class InventoryItem(models.Model):
    ABC_CHOICES = [
        ('A', 'Class A — High Value (70%)'),
        ('B', 'Class B — Medium Value (20%)'),
        ('C', 'Class C — Low Value (10%)'),
        ('U', 'Unclassified'),
    ]

    product_id   = models.CharField(max_length=20, unique=True, editable=False) 
    item_name    = models.CharField(max_length=200)
    category     = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    supplier     = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    description  = models.TextField(blank=True)
    barcode_id   = models.CharField(max_length=50, unique=True)
    
    price        = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal('0.00'))])
    unit_cost    = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal('0.00'))])
    quantity     = models.PositiveIntegerField(default=0)
    annual_demand = models.PositiveIntegerField(default=0)
    
    # --- NEW FIELDS FOR ROP & LEAD TIME COMPUTATION ---
    average_daily_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Average items sold per day")
    max_daily_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Highest number of items sold in a single day")
    average_lead_time_days = models.PositiveIntegerField(default=0, help_text="Average days for supplier to deliver")
    max_lead_time_days = models.PositiveIntegerField(default=0, help_text="Maximum days it took for a delivery to arrive")
    
    # These will be auto-calculated now, so we can make them editable=False (optional, but good for data integrity)
    safety_stock = models.PositiveIntegerField(default=0, editable=False)
    reorder_point = models.PositiveIntegerField(default=10) # Overwritten during save()
    # ---------------------------------------------------

    manual_annual_demand = models.PositiveIntegerField(default=0)
    actual_sales_count = models.PositiveIntegerField(default=0)

    abc_classification = models.CharField(max_length=1, choices=ABC_CHOICES, default='U')

    date_added   = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory'
        ordering = ['item_name']

    @property
    def name(self):
        return self.item_name

    @property
    def annual_consumption_value(self):
        """Formula: Unit Cost * Annual Demand"""
        return self.unit_cost * self.annual_demand

    def save(self, *args, **kwargs):
        # 1. Generate Product ID 
        if not self.product_id:
            prefix = self.category.prefix.upper()
            last_item = InventoryItem.objects.filter(category=self.category).order_by('id').last()
            if not last_item:
                new_no = 1
            else:
                numeric_matches = re.findall(r'\d+', last_item.product_id)
                new_no = int(numeric_matches[-1]) + 1 if numeric_matches else 1
            self.product_id = f"{prefix}{new_no:03d}"

        # 2. ROP & Safety Stock Computation
        avg_sales = float(self.average_daily_sales or 0)
        max_sales = float(self.max_daily_sales or 0)
        avg_lt = float(self.average_lead_time_days or 0)
        max_lt = float(self.max_lead_time_days or 0)
        
        lead_time_demand = avg_sales * avg_lt
        max_lt_demand = max_sales * max_lt
        raw_safety_stock = max_lt_demand - lead_time_demand
        
        self.safety_stock = int(max(0, round(raw_safety_stock)))
        self.reorder_point = int(round(lead_time_demand)) + self.safety_stock

        # 3. TRIGGER AUTOMATIC NOTIFICATION
        # We use apps.get_model to prevent circular import errors in Django
        from django.apps import apps
        Notification = apps.get_model('notifications', 'Notification')
        
        if int(self.quantity) <= self.reorder_point:            # Check if an UNREAD notification already exists for this item to prevent spam
            existing_alert = Notification.objects.filter(
                notification_type='low_stock',
                source_table='inventory',
                source_id=str(self.id),
                is_read=False
            ).exists()
            
            if not existing_alert:
                # Prioritize alerts based on ABC Classification
                urgency = 'critical' if self.abc_classification == 'A' else ('high' if self.abc_classification == 'B' else 'medium')
                
                Notification.objects.create(
                    notification_type='low_stock',
                    priority=urgency,
                    title=f"Low Stock: {self.item_name}",
                    message=f"Stock is down to {self.quantity} units (Reorder Point: {self.reorder_point}). Generating a Purchase Order is highly recommended to avoid shortages.",
                    source_table='inventory',
                    source_id=str(self.id),
                    action_url="/inventory/purchase-orders/create/?auto=true"                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} ({self.category.prefix})"   
# I-register ang InventoryItem (para ma-track ang edits sa products/quantity/price)
auditlog.register(InventoryItem)

# (Optional) Pwede mo rin i-register ang iba kung gusto mo i-track pag may nag-edit ng supplier o category
auditlog.register(Category)
auditlog.register(Supplier)

# --- PURCHASE ORDER (PO) SYSTEM ---

class PurchaseOrder(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('pending', 'Pending Delivery'),
        ('received', 'Received / Completed'),
        ('cancelled', 'Cancelled'),
    )

    po_number = models.CharField(max_length=50, unique=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.RESTRICT, related_name='purchase_orders')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    order_date = models.DateTimeField(default=timezone.now)
    expected_delivery = models.DateField(blank=True, null=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    class Meta:
        db_table = 'purchase_orders'
        ordering = ['-order_date']

    def save(self, *args, **kwargs):
        if not self.po_number:
            today = timezone.now().strftime('%Y%m%d')
            last = PurchaseOrder.objects.filter(
                po_number__startswith=f'PO-{today}'
            ).order_by('id').last()
            seq = (int(last.po_number.split('-')[-1]) + 1) if last else 1
            self.po_number = f'PO-{today}-{seq:03d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.po_number} - {self.supplier.name}"


def save(self, *args, **kwargs):
        # 1. Generate Product ID 
        if not self.product_id:
            prefix = self.category.prefix.upper()
            last_item = InventoryItem.objects.filter(category=self.category).order_by('id').last()
            if not last_item:
                new_no = 1
            else:
                numeric_matches = re.findall(r'\d+', last_item.product_id)
                new_no = int(numeric_matches[-1]) + 1 if numeric_matches else 1
            self.product_id = f"{prefix}{new_no:03d}"

        # 2. ROP & Safety Stock Computation
        # Kinonvert natin sa float lahat para safe at hindi mag-crash!
        avg_sales = float(self.average_daily_sales or 0)
        max_sales = float(self.max_daily_sales or 0)
        avg_lt = float(self.average_lead_time_days or 0)
        max_lt = float(self.max_lead_time_days or 0)
        
        # Dahil lahat sila ay purong numbers na, pwede na i-multiply:
        lead_time_demand = avg_sales * avg_lt
        
        max_lt_demand = max_sales * max_lt
        raw_safety_stock = max_lt_demand - lead_time_demand
        
        self.safety_stock = int(max(0, round(raw_safety_stock)))
        self.reorder_point = int(round(lead_time_demand)) + self.safety_stock

        super().save(*args, **kwargs)

def __str__(self):
        return f"{self.po_number} - {self.supplier.name}"


class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, related_name='items', on_delete=models.CASCADE)
    
    # Linked directly to your existing InventoryItem!
    product = models.ForeignKey(InventoryItem, on_delete=models.RESTRICT) 
    
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    
    # This is the cost from the supplier (which might differ from your current unit_cost)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2) 
    
    class Meta:
        db_table = 'purchase_order_items'

    @property
    def subtotal(self):
        return self.quantity_ordered * self.unit_cost

    def __str__(self):
        return f"{self.quantity_ordered}x {self.product.item_name} for {self.purchase_order.po_number}"

# (Optional) Track Purchase Orders in your audit log
auditlog.register(PurchaseOrder)