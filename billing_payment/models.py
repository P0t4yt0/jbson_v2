"""
Module 5 — Billing & Payment
Processes payment for a completed POS transaction.
Supports: Cash | Mobile Wallet (GCash, Maya, etc.)
Generates official receipts and updates inventory on success.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
import uuid


class Payment(models.Model):
    """
    Financial settlement record linked to a POS Transaction.
    One transaction → one payment record.
    """
    PAYMENT_METHOD_CHOICES = [
        ('cash',   'Cash'),
        ('gcash',  'GCash'),
        ('maya',   'Maya'),
        ('wallet', 'Other Mobile Wallet'),
    ]

    STATUS_CHOICES = [
        ('pending',  'Pending'),
        ('success',  'Success'),
        ('failed',   'Failed'),
        ('refunded', 'Refunded'),
    ]

    transaction     = models.OneToOneField(
        'point_of_sale.Transaction', on_delete=models.CASCADE,
        related_name='payment'
    )
    processed_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='payments'
    )
    payment_method  = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
    amount_due      = models.DecimalField(max_digits=12, decimal_places=2)
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_amount   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    reference_number = models.CharField(max_length=50, blank=True)   # e.g. GCash ref
    date_created    = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'payments'
        ordering = ['-date_created']

    def save(self, *args, **kwargs):
        # Auto-compute change for cash payments
        if self.payment_method == 'cash' and self.amount_tendered >= self.amount_due:
            self.change_amount = self.amount_tendered - self.amount_due
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Payment for {self.transaction.transaction_ref} — ₱{self.amount_due} ({self.get_payment_method_display()})'


class Receipt(models.Model):
    """
    Official receipt generated after successful payment.
    Stored as a PDF file path for printing/re-printing.
    """
    payment         = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='receipt')
    receipt_number  = models.CharField(max_length=30, unique=True, editable=False)
    pdf_file        = models.FileField(upload_to='receipts/', blank=True, null=True)
    date_issued     = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'receipts'
        ordering = ['-date_issued']

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            today = timezone.now().strftime('%Y%m%d')
            short = uuid.uuid4().hex[:6].upper()
            self.receipt_number = f'RCP-{today}-{short}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Receipt {self.receipt_number} — {self.date_issued:%Y-%m-%d %H:%M}'
