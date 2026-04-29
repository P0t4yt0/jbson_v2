"""
Module 2 — Inventory Management
Tracks all products with ABC Analysis classification (A/B/C).
ABC logic: items sorted by value (price × qty), cumulative % determines class.
  A = top 70%  (high-value  → priority alerts)
  B = 70-90%   (mid-value)
  C = 90-100%  (low-value)
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


class Category(models.Model):
    """Product categories (e.g. Paint, Cement, Tools, Fasteners)."""
    name        = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = 'categories'
        ordering  = ['name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Supplier(models.Model):
    """Supplier / vendor information."""
    name         = models.CharField(max_length=150)
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
    Each item has a barcode (scanned or system-generated 1D),
    ABC classification, and real-time stock tracking.
    """
    ABC_CHOICES = [
        ('A', 'Class A — High Value'),
        ('B', 'Class B — Medium Value'),
        ('C', 'Class C — Low Value'),
        ('U', 'Unclassified'),
    ]

    # ── Identity ───────────────────────────────────────────────────────────
    product_id   = models.CharField(max_length=20, unique=True)    # e.g. PT001
    item_name    = models.CharField(max_length=200)
    category     = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='items')
    supplier     = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    description  = models.TextField(blank=True)

    # ── Barcode ────────────────────────────────────────────────────────────
    barcode_id         = models.CharField(max_length=50, unique=True)
    barcode_generated  = models.BooleanField(default=False)  # True = system-generated 1D
    barcode_image      = models.ImageField(upload_to='barcodes/', blank=True, null=True)

    # ── Pricing & Stock ────────────────────────────────────────────────────
    price        = models.DecimalField(max_digits=10, decimal_places=2)
    quantity     = models.PositiveIntegerField(default=0)
    min_stock    = models.PositiveIntegerField(default=10)   # Low-stock threshold

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

    @property
    def is_low_stock(self):
        return self.quantity <= self.min_stock

    @property
    def stock_value(self):
        """Total value of stock on hand (price × quantity)."""
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
