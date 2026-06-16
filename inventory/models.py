import re
from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from auditlog.registry import auditlog

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
        return self.name

class Supplier(models.Model):
    supplier_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)
    contact_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    default_lead_time_days = models.PositiveIntegerField(default=7, help_text="Standard days to deliver")
    max_lead_time_days = models.PositiveIntegerField(default=14, help_text="Maximum expected delay")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']

    def __str__(self):
        return self.name

class InventoryItem(models.Model):
    ABC_CHOICES = [
        ('A', 'Class A — High Value (70%)'),
        ('B', 'Class B — Medium Value (20%)'),
        ('C', 'Class C — Low Value (10%)'),
        ('U', 'Unclassified'),
    ]

    barcode_validator = RegexValidator(
        regex=r'^\d{13}$',
        message="Barcode must be exactly 13 digits long and contain only numbers (EAN-13 standard)."
    )

    product_id = models.CharField(max_length=20, unique=True, editable=False) 
    item_name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    description = models.TextField(blank=True)
    barcode_id = models.CharField(max_length=50, unique=True, validators=[barcode_validator])
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal('0.00'))])
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, validators=[MinValueValidator(Decimal('0.00'))])
    quantity = models.PositiveIntegerField(default=0)
    annual_demand = models.PositiveIntegerField(default=0)
    average_daily_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Average items sold per day")
    max_daily_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Highest number of items sold in a single day")
    average_lead_time_days = models.PositiveIntegerField(default=0, help_text="Leave as 0 to use Supplier's default")
    max_lead_time_days = models.PositiveIntegerField(default=0, help_text="Leave as 0 to use Supplier's maximum")    
    safety_stock = models.PositiveIntegerField(default=0, editable=False)
    reorder_point = models.PositiveIntegerField(default=10)
    manual_annual_demand = models.PositiveIntegerField(default=0)
    actual_sales_count = models.PositiveIntegerField(default=0)
    abc_classification = models.CharField(max_length=1, choices=ABC_CHOICES, default='U')
    date_added = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory'
        ordering = ['item_name']

    @property
    def name(self):
        return self.item_name

    @property
    def annual_consumption_value(self):
        return self.unit_cost * self.annual_demand

    # Fix #1: Engine helper para sa automated FEFO Allocation tuwing may bawas mula sa POS Checkout
    def deduct_stock_fefo(self, qty_to_deduct):
        """
        Deducts stock smoothly across underlying batches using First-Expired, First-Out (FEFO).
        Saves changes instantly to avoid synchronization loops.
        """
        if qty_to_deduct > self.quantity:
            raise ValidationError(f"Cannot deduct {qty_to_deduct} units. Only {self.quantity} items available on hand.")
        
        # Kunin ang mga usable batches na may stock pa, unahin ang pinakamalapit mag-expire
        usable_batches = self.batches.filter(status__in=['active', 'near_expiry'], quantity_on_hand__gt=0).order_index_fefo()
        
        remaining_deduction = qty_to_deduct
        for batch in usable_batches:
            if remaining_deduction <= 0:
                break
            
            if batch.quantity_on_hand >= remaining_deduction:
                batch.quantity_on_hand -= remaining_deduction
                remaining_deduction = 0
            else:
                remaining_deduction -= batch.quantity_on_hand
                batch.quantity_on_hand = 0
                
            batch.save(update_stock_master=False) # Iwas looping overwrite

        # I-update ang global cache quantity
        self.quantity = max(0, self.quantity - qty_to_deduct)
        self.save(skip_batch_recalc=True)

    def add_stock_fefo(self, qty_to_add):
        """
        Handles returns or stock additions gracefully by putting the inventory back 
        into the oldest active batch or latest batch received.
        """
        target_batch = self.batches.filter(status__in=['active', 'near_expiry']).order_by('expiry_date', 'date_received').first()
        if target_batch:
            target_batch.quantity_on_hand += qty_to_add
            target_batch.save(update_stock_master=False)
        
        self.quantity += qty_to_add
        self.save(skip_batch_recalc=True)

    def save(self, *args, **kwargs):
        # Flag parameter to bypass automatic batch calculation locks if running custom FEFO pipeline
        skip_batch_recalc = kwargs.pop('skip_batch_recalc', False)

        if not self.product_id:
            if self.category and self.category.prefix:
                prefix = self.category.prefix.replace(" ", "").strip().upper()
            else:
                safe_name = self.category.name.replace(" ", "").strip()
                prefix = safe_name[:3].upper().ljust(3, 'X')

            existing_items = InventoryItem.objects.filter(product_id__icontains=prefix)
            max_num = 0
            for item in existing_items:
                numeric_matches = re.findall(r'\d+', item.product_id)
                if numeric_matches:
                    num = int(numeric_matches[-1])
                    if num > max_num:
                        max_num = num
                        
            self.product_id = f"{prefix}{(max_num + 1):03d}"

        # Huwag i-recalculate kung pinigilan ng dynamic logic system natin
        if not skip_batch_recalc and self.pk:
            usable_batches = self.batches.filter(status__in=['active', 'near_expiry'])
            self.quantity = sum(batch.quantity_on_hand for batch in usable_batches)

        avg_sales = float(self.average_daily_sales or 0)
        max_sales = float(self.max_daily_sales or 0)
        avg_lt = float(self.average_lead_time_days)
        max_lt = float(self.max_lead_time_days)
        
        if avg_lt == 0 and self.supplier:
            avg_lt = float(self.supplier.default_lead_time_days)
            
        if max_lt == 0 and self.supplier:
            max_lt = float(self.supplier.max_lead_time_days)
        
        lead_time_demand = avg_sales * avg_lt
        max_lt_demand = max_sales * max_lt
        raw_safety_stock = max_lt_demand - lead_time_demand
        
        self.safety_stock = int(max(0, round(raw_safety_stock)))
        computed_rop = int(round(lead_time_demand)) + self.safety_stock

        MINIMUM_ROP = 5
        self.reorder_point = max(computed_rop, MINIMUM_ROP)

        from django.apps import apps
        Notification = apps.get_model('notifications', 'Notification')
        
        if int(self.quantity) <= self.reorder_point:
            existing_alert = Notification.objects.filter(
                notification_type='low_stock',
                source_table='inventory',
                source_id=str(self.id),
                is_read=False
            ).exists()
            
            if not existing_alert:
                urgency = 'critical' if self.abc_classification == 'A' else ('high' if self.abc_classification == 'B' else 'medium')
                
                Notification.objects.create(
                    notification_type='low_stock',
                    priority=urgency,
                    title=f"Low Stock: {self.item_name}",
                    message=f"Stock is down to {self.quantity} units (Reorder Point: {self.reorder_point}). Generating a Purchase Order is highly recommended to avoid shortages.",
                    source_table='inventory',
                    source_id=str(self.id),
                    action_url="/inventory/purchase-orders/create/?auto=true"
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.item_name} ({self.category.prefix})"


class ProductBatchQuerySet(models.QuerySet):
    def order_index_fefo(self):
        # Custom prioritization framework: Expiry dates first, then order sequence
        return self.order_by('expiry_date', 'date_received', 'id')


class ProductBatch(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('near_expiry', 'Near Expiry'),
        ('expired', 'Expired'),
        ('pulled_out', 'Pulled Out/Disposed'),
    )

    product = models.ForeignKey('InventoryItem', on_delete=models.CASCADE, related_name='batches')
    batch_code = models.CharField(max_length=50, unique=True, blank=True) 
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_on_hand = models.PositiveIntegerField(default=0)
    
    date_received = models.DateField(default=timezone.now)
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')

    objects = ProductBatchQuerySet.as_manager()

    class Meta:
        db_table = 'product_batches'
        ordering = ['expiry_date', 'date_received'] 

    def save(self, *args, **kwargs):
        update_stock_master = kwargs.pop('update_stock_master', True)

        if not self.batch_code:
            today_str = timezone.now().strftime('%y%m%d')
            prefix = self.product.product_id if self.product.product_id else 'UNK'
            
            existing_batches_today = ProductBatch.objects.filter(
                product=self.product, 
                date_received=self.date_received
            ).count()
            
            sequence = f"{(existing_batches_today + 1):02d}"
            self.batch_code = f"BCH-{prefix}-{today_str}-{sequence}"

        super().save(*args, **kwargs)
        
        if update_stock_master:
            self.update_parent_stock()

    def update_parent_stock(self):
        usable_batches = ProductBatch.objects.filter(
            product=self.product, 
            status__in=['active', 'near_expiry']
        )
        total_qty = sum(batch.quantity_on_hand for batch in usable_batches)
        
        # Gamitin ang override flag para maiwasan ang operational deadlocks sa model save state
        self.product.quantity = total_qty
        self.product.save(update_fields=['quantity'], skip_batch_recalc=True)

    def __str__(self):
        return f"{self.batch_code} - {self.product.item_name}"

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
            existing_pos = PurchaseOrder.objects.filter(po_number__startswith=f'PO-{today}')
            max_num = 0
            for po in existing_pos:
                try:
                    num = int(po.po_number.split('-')[-1])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    continue
            self.po_number = f'PO-{today}-{(max_num + 1):03d}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.po_number} - {self.supplier.name}"

class PurchaseOrderItem(models.Model):
    purchase_order = models.ForeignKey(PurchaseOrder, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(InventoryItem, on_delete=models.RESTRICT) 
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2) 

    class Meta:
        db_table = 'purchase_order_items'

    @property
    def subtotal(self):
        return self.quantity_ordered * self.unit_cost

    def __str__(self):
        return f"{self.quantity_ordered}x {self.product.item_name} for {self.purchase_order.po_number}"

class GeneratedBarcode(models.Model):
    # Fix #6: I-apply din ang strict 13-digit pattern validation sa generated tracking module
    barcode_validator = RegexValidator(
        regex=r'^\d{13}$',
        message="Barcode must be exactly 13 digits long and contain only numbers."
    )

    barcode_id = models.CharField(max_length=50, unique=True, validators=[barcode_validator])
    product_name = models.CharField(max_length=200)
    batch_id = models.CharField(max_length=50, default='MANUAL')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'generated_barcodes'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.product_name} - {self.barcode_id}"

auditlog.register(Category)
auditlog.register(Supplier)
auditlog.register(InventoryItem)
auditlog.register(PurchaseOrder)