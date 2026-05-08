"""
Module 4 — Point of Sale (POS)
Handles sales transactions. Each Transaction contains multiple TransactionItems.
On completion, inventory stock is automatically decremented.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


class Transaction(models.Model):
    """
    A single POS sales session/transaction.
    Status flow: open → completed | voided
    """
    STATUS_CHOICES = [
        ('open',      'Open'),        # Items being scanned
        ('completed', 'Completed'),   # Payment confirmed
        ('voided',    'Voided'),      # Transaction cancelled
    ]

    PAYMENT_CHOICES = [
        ('Cash', 'Cash'),
        ('Online Wallet', 'Online Wallet'),
    ]

    payment_method = models.CharField(
        max_length=20, 
        choices=PAYMENT_CHOICES, 
        default='Cash'
    )

    transaction_ref = models.CharField(max_length=20, unique=True, editable=False)
    processed_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='transactions'
    )
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    void_reason     = models.TextField(blank=True)
    date_created    = models.DateTimeField(default=timezone.now)
    date_completed  = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'pos_transactions'
        ordering = ['-date_created']
        indexes  = [models.Index(fields=['transaction_ref'])]

    def save(self, *args, **kwargs):
        # Auto-generate transaction reference: TXN-YYYYMMDD-XXXX
        if not self.transaction_ref:
            today = timezone.now().strftime('%Y%m%d')
            short = uuid.uuid4().hex[:6].upper()
            self.transaction_ref = f'TXN-{today}-{short}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.transaction_ref} — ₱{self.total_amount} ({self.get_status_display()})'

    def calculate_totals(self):
        """Recalculate subtotal and total from items."""
        items = self.items.all()
        self.subtotal    = sum(item.subtotal for item in items)
        self.total_amount = self.subtotal
        self.save(update_fields=['subtotal', 'total_amount'])


class TransactionItem(models.Model):
    """
    A single line item within a Transaction.
    Stores a snapshot of price at time of sale (price may change later).
    """
    transaction     = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    inventory_item  = models.ForeignKey(
        'inventory.InventoryItem', on_delete=models.PROTECT,
        related_name='sold_items'
    )
    quantity        = models.PositiveIntegerField(default=1)
    unit_price      = models.DecimalField(max_digits=10, decimal_places=2)  # Price at time of sale
    subtotal        = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = 'pos_transaction_items'

    def save(self, *args, **kwargs):
        self.subtotal = self.unit_price * self.quantity
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.inventory_item.item_name} × {self.quantity} = ₱{self.subtotal}'
