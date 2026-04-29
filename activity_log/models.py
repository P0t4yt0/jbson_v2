"""
Module 7 — Activity Log
Immutable audit trail of all user actions.
Records: logins, logouts, product changes, sales, adjustments, etc.
Admin-only view. Logs cannot be modified or deleted.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


class ActivityLog(models.Model):
    """
    Append-only log of every significant system action.
    Immutability is enforced at the model level (no update/delete signals).
    """
    ACTION_CHOICES = [
        # Auth
        ('login',              'User Login'),
        ('logout',             'User Logout'),
        ('login_failed',       'Failed Login Attempt'),
        # User Management
        ('user_created',       'User Created'),
        ('user_updated',       'User Updated'),
        ('user_deactivated',   'User Deactivated'),
        # Inventory
        ('item_added',         'Item Added'),
        ('item_updated',       'Item Updated'),
        ('item_deleted',       'Item Deleted'),
        ('stock_adjusted',     'Stock Adjusted'),
        ('barcode_generated',  'Barcode Generated'),
        # POS & Billing
        ('transaction_started','Transaction Started'),
        ('transaction_completed','Transaction Completed'),
        ('transaction_voided', 'Transaction Voided'),
        ('payment_processed',  'Payment Processed'),
        ('receipt_generated',  'Receipt Generated'),
        # Reports
        ('report_generated',   'Report Generated'),
        # Maintenance
        ('backup_created',     'Backup Created'),
        ('restore_performed',  'Restore Performed'),
        # CSV
        ('csv_imported',       'CSV Imported'),
    ]

    user         = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='activity_logs'
    )
    action       = models.CharField(max_length=30, choices=ACTION_CHOICES)
    description  = models.TextField(blank=True)     # Human-readable detail
    source_table = models.CharField(max_length=50, blank=True)  # e.g. 'inventory'
    source_id    = models.CharField(max_length=50, blank=True)  # PK of affected record
    ip_address   = models.GenericIPAddressField(null=True, blank=True)
    date_created = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'activity_logs'
        ordering = ['-date_created']
        indexes  = [
            models.Index(fields=['user']),
            models.Index(fields=['action']),
            models.Index(fields=['date_created']),
        ]

    def __str__(self):
        username = self.user.username if self.user else 'System'
        return f'[{self.date_created:%Y-%m-%d %H:%M}] {username} — {self.get_action_display()}'

    def save(self, *args, **kwargs):
        # Prevent updates — activity logs are write-once
        if self.pk:
            raise PermissionError('Activity logs are immutable and cannot be modified.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('Activity logs cannot be deleted.')
