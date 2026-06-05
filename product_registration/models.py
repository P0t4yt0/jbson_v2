from django.conf import settings
from django.db import models
from django.utils import timezone

class ProductRegistrationLog(models.Model):
    SOURCE_CHOICES = [
        ('manual', 'Manual Entry'),
        ('scan', 'Barcode Scan'),
        ('csv', 'CSV Import'),
        ('generated', 'System Generated Barcode'),
    ]

    inventory_item = models.ForeignKey('inventory.InventoryItem', on_delete=models.CASCADE, related_name='registration_logs')
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    source = models.CharField(max_length=15, choices=SOURCE_CHOICES, default='manual')
    barcode_value = models.CharField(max_length=50)
    notes = models.TextField(blank=True)
    registered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'product_registration_logs'
        ordering = ['-registered_at']

    def __str__(self):
        return f'{self.inventory_item.item_name} — {self.get_source_display()} @ {self.registered_at:%Y-%m-%d %H:%M}'

class CSVImportLog(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('partial', 'Partial — Some rows failed'),
        ('failed', 'Failed'),
    ]

    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file_name = models.CharField(max_length=255)
    total_rows = models.PositiveIntegerField(default=0)
    success_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error_details = models.TextField(blank=True)
    imported_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'csv_import_logs'
        ordering = ['-imported_at']

    def __str__(self):
        return f'CSV Import: {self.file_name} — {self.get_status_display()} ({self.imported_at:%Y-%m-%d})'