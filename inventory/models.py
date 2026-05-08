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
    reorder_point = models.PositiveIntegerField(default=10)
    manual_annual_demand = models.PositiveIntegerField(default=0)
    actual_sales_count = models.PositiveIntegerField(default=0)

    abc_classification = models.CharField(max_length=1, choices=ABC_CHOICES, default='U')

    date_added   = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'inventory'
        ordering = ['item_name']

    @property
    def annual_consumption_value(self):
        """Formula: Unit Cost * Annual Demand"""
        return self.unit_cost * self.annual_demand

    def save(self, *args, **kwargs):
        if not self.product_id:
            prefix = self.category.prefix.upper()
            last_item = InventoryItem.objects.filter(category=self.category).order_by('id').last()
            if not last_item:
                new_no = 1
            else:
                numeric_matches = re.findall(r'\d+', last_item.product_id)
                new_no = int(numeric_matches[-1]) + 1 if numeric_matches else 1
            self.product_id = f"{prefix}{new_no:03d}"
        super().save(*args, **kwargs)
    def __str__(self):
       return f"{self.name} ({self.prefix})"    
# I-register ang InventoryItem (para ma-track ang edits sa products/quantity/price)
auditlog.register(InventoryItem)

# (Optional) Pwede mo rin i-register ang iba kung gusto mo i-track pag may nag-edit ng supplier o category
auditlog.register(Category)
auditlog.register(Supplier)