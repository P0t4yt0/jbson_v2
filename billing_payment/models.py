"""
Module 5 — Billing & Payment
Processes payment for a completed POS transaction.
Supports: Cash | Mobile Wallet (GCash, Maya, etc.)
Generates official receipts and updates inventory on success.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import uuid
from point_of_sale.models import Transaction

# --- 1. CUSTOMER TABLE ---
class Customer(models.Model):
    name = models.CharField(max_length=150, unique=True)
    phone = models.CharField(max_length=20, blank=True)
    
    # Trade Credit Core Fields
    is_credit_customer = models.BooleanField(default=False)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00) # How much they owe
    
    TERMS_CHOICES = [(30, 'Net 30'), (60, 'Net 60'), (90, 'Net 90')]
    payment_terms = models.IntegerField(choices=TERMS_CHOICES, default=30)
    
    STATUS_CHOICES = [('active', 'Active'), ('hold', 'Hold')]
    credit_status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='active')

    class Meta:
        db_table = 'customers'

    def __str__(self):
        return self.name

    @property
    def available_credit(self):
        return self.credit_limit - self.credit_balance

    def check_overdue_status(self):
        """Rule 3: Overdue protection. Puts account on hold if invoices are overdue."""
        if self.invoices.filter(status='overdue').exists():
            self.credit_status = 'hold'
            self.save(update_fields=['credit_status'])
            return True
        return False

# --- 2. INVOICE TABLE ---
class Invoice(models.Model):
    SOURCE_CHOICES = [('manual', 'Manual Entry'), ('pos', 'POS System')]
    STATUS_CHOICES = [('unpaid', 'Unpaid'), ('overdue', 'Overdue'), ('paid', 'Paid')]

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='manual')
    transaction = models.OneToOneField('point_of_sale.Transaction', on_delete=models.CASCADE, related_name='invoice', null=True, blank=True)
    invoice_no = models.CharField(max_length=20, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='invoices', null=True, blank=True)
    
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    issue_date = models.DateField(default=timezone.now)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unpaid')

    class Meta:
        db_table = 'invoices'

    def save(self, *args, **kwargs):
        if not self.invoice_no:
            today = timezone.now().strftime('%Y%m')
            short = uuid.uuid4().hex[:5].upper()
            self.invoice_no = f'INV-{today}-{short}'
            
        # Auto-calculate due date based on customer terms kung wala pang nakalagay
        if not self.due_date and self.customer_id:
            self.due_date = self.issue_date + timedelta(days=self.customer.payment_terms)
            
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.invoice_no} - {self.customer.name}"

# --- 2.1 INVOICE ITEMS (Para sa Manual Create Invoice) ---
class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='items')
    product_name = models.CharField(max_length=255)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.product_name} on {self.invoice.invoice_no}"

# --- 3. PAYMENTS AGAINST TRADE CREDIT ---
class InvoicePayment(models.Model):
    invoice = models.ForeignKey('Invoice', on_delete=models.CASCADE, related_name='payments')    
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=[('cash', 'Cash'), ('bank', 'Online Bank')])
    date = models.DateTimeField(default=timezone.now)
    processed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        db_table = 'invoice_payments'

    def save(self, *args, **kwargs):
        if not self.pk: 
            self.invoice.balance_due -= self.amount
            if self.invoice.balance_due <= 0:
                self.invoice.status = 'paid'
            self.invoice.save()

            self.invoice.customer.credit_balance -= self.amount
            if self.invoice.customer.credit_balance <= 0:
                self.invoice.customer.credit_status = 'active'
            self.invoice.customer.save()
            
        super().save(*args, **kwargs)

# --- 4. POS PAYMENTS & RECEIPTS ---
class Payment(models.Model):
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

    transaction     = models.OneToOneField('point_of_sale.Transaction', on_delete=models.CASCADE, related_name='payment')
    processed_by    = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='payments')
    payment_method  = models.CharField(max_length=10, choices=PAYMENT_METHOD_CHOICES)
    amount_due      = models.DecimalField(max_digits=12, decimal_places=2)
    amount_tendered = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    change_amount   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status          = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    reference_number = models.CharField(max_length=50, blank=True)
    date_created    = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'payments'
        ordering = ['-date_created']

    def save(self, *args, **kwargs):
        if self.payment_method == 'cash' and self.amount_tendered >= self.amount_due:
            self.change_amount = self.amount_tendered - self.amount_due
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Payment for {self.transaction.transaction_ref} — ₱{self.amount_due} ({self.get_payment_method_display()})'

class Receipt(models.Model):
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