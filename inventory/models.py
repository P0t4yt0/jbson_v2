"""
Module 2 — Inventory Management
Tracks all products with ABC Analysis classification (A/B/C).
ABC logic: items sorted by value (price × qty), cumulative % determines class.
  A = top 70%  (high-value  → priority alerts)
  B = 70-90%   (mid-value)
  C = 90-100%  (low-value)
"""
import re
from django.db import models
from django.conf import settings
from django.utils import timezone


class Category(models.Model):
    """Product categories with prefix for ID generation."""
    name = models.CharField(max_length=100, unique=True)
    # New Field: Prefix (e.g., PT, CM, TL)
    prefix = models.CharField(max_length=5, unique=True, help_text="2-5 letter code for IDs")
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'categories'
        ordering = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return f"{self.name} ({self.prefix})"


class Supplier(models.Model):
    """Supplier / vendor information."""
    supplier_id = models.CharField(max_length=20, unique=True, null=True, blank=True)
    name = models.CharField(max_length=100)
    contact_name = models.CharField(max_length=100, blank=True)
    phone        = models.CharField(max_length=20, blank=True)
    email        = models.EmailField(blank=True)
    address      = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'suppliers'
        ordering = ['name']

    def __str__(self):
        return self.name


class InventoryItem(models.Model):
    """
    Core inventory record.
    Automated product_id generation based on Category prefix.
    """
    ABC_CHOICES = [
        ('A', 'Class A — High Value'),
        ('B', 'Class B — Medium Value'),
        ('C', 'Class C — Low Value'),
        ('U', 'Unclassified'),
    ]

    # ── Identity ───────────────────────────────────────────────────────────
    # Set editable=False because the system generates this automatically
    product_id   = models.CharField(max_length=20, unique=True, editable=False) 
    item_name    = models.CharField(max_length=200)
    category     = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    supplier     = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    description  = models.TextField(blank=True)

    # ── Barcode ────────────────────────────────────────────────────────────
    barcode_id         = models.CharField(max_length=50, unique=True)
    barcode_generated  = models.BooleanField(default=False)
    barcode_image       = models.ImageField(upload_to='barcodes/', blank=True, null=True)

    # ── Pricing & Stock ────────────────────────────────────────────────────
    price        = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField(default=0)
    min_stock    = models.PositiveIntegerField(default=10)

    # ── ABC Classification ─────────────────────────────────────────────────
    abc_classification = models.CharField(max_length=1, choices=ABC_CHOICES, default='U')

    # ── Timestamps ─────────────────────────────────────────────────────────
    date_added   = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)
    added_by     = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='added_items'
    )

    class Meta:
        db_table = 'inventory'
        ordering = ['item_name']
        indexes  = [
            models.Index(fields=['product_id']),
            models.Index(fields=['barcode_id']),
            models.Index(fields=['item_name']),
            models.Index(fields=['abc_classification']),
        ]

    def __str__(self):
        return f'[{self.product_id}] {self.item_name}'

    def save(self, *args, **kwargs):
        """Automates the generation of category-based Product IDs[cite: 1]"""
        if not self.product_id:
            # 1. Get Prefix from the chosen Category
            prefix = self.category.prefix.upper()
            
            # 2. Look for the latest item in this specific category[cite: 1]
            last_item = InventoryItem.objects.filter(category=self.category).order_by('id').last()
            
            if not last_item:
                new_no = 1
            else:
                # 3. Extract the numeric part of the ID (e.g., PT015 -> 15)[cite: 1]
                numeric_matches = re.findall(r'\d+', last_item.product_id)
                if numeric_matches:
                    new_no = int(numeric_matches[-1]) + 1
                else:
                    new_no = 1

            # 4. Final Format: Prefix + 3-digit number (e.g., PT001)[cite: 1]
            self.product_id = f"{prefix}{new_no:03d}"
            
        super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock

    @property
    def stock_value(self):
        return self.price * self.quantity

    @property
    def stock_status(self):
        if self.quantity == 0:
            return 'Out of Stock'
        elif self.is_low_stock:
            return 'Low Stock'
        return 'In Stock'


class StockAdjustment(models.Model):
    """
    Manual stock adjustments — supplier deliveries, damage, shrinkage.
    Keeps a full audit trail of every quantity change.
    """
    REASON_CHOICES = [
        ('delivery',  'Supplier Delivery'),
        ('damage',    'Damaged Goods'),
        ('shrinkage', 'Shrinkage / Loss'),
        ('correction','Stock Correction'),
        ('return',    'Customer Return'),
        ('other',     'Other'),
    ]

    item         = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, related_name='adjustments')
    adjusted_by  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    reason       = models.CharField(max_length=20, choices=REASON_CHOICES)
    quantity_before = models.IntegerField()
    quantity_change = models.IntegerField()   # Positive = add | Negative = deduct
    quantity_after  = models.IntegerField()
    notes        = models.TextField(blank=True)
    date_adjusted = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'stock_adjustments'
        ordering = ['-date_adjusted']

    def __str__(self):
        direction = '+' if self.quantity_change >= 0 else ''
        return f'{self.item.item_name} {direction}{self.quantity_change} ({self.get_reason_display()})'
