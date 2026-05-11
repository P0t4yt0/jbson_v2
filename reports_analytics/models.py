"""
Module 6 — Reports & Analytics
Stores generated report metadata and file paths.
Reports are built using SQL aggregate functions on live data,
then exported as PDF. Admin-only access.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


class Report(models.Model):
    """
    Metadata record for every generated report.
    The actual PDF is stored in media/reports/.
    """
    REPORT_TYPE_CHOICES = [
        ('sales_summary',   'Sales Summary'),
        ('sales_daily',     'Daily Sales Report'),
        ('sales_weekly',    'Weekly Sales Report'),
        ('sales_monthly',   'Monthly Sales Report'),
        ('sales_annual',    'Annual Sales Report'),
        ('inventory',       'Inventory Report'),
        ('low_stock',       'Low Stock Report'),
        ('abc_analysis',    'ABC Analysis Report'),
        ('financial',       'Financial Overview'),
        ('purchase',        'Purchase Report'),
    ]

    PERIOD_CHOICES = [
        ('daily',   'Daily'),
        ('weekly',  'Weekly'),
        ('monthly', 'Monthly'),
        ('yearly',  'Yearly'),
        ('custom',  'Custom Range'),
    ]

    generated_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='reports'
    )
    report_type   = models.CharField(max_length=20, choices=REPORT_TYPE_CHOICES)
    period        = models.CharField(max_length=10, choices=PERIOD_CHOICES, default='daily')
    date_from     = models.DateField(null=True, blank=True)
    date_to       = models.DateField(null=True, blank=True)
    file_path     = models.FileField(upload_to='reports/', blank=True, null=True)
    source_table  = models.CharField(max_length=50, blank=True)   # e.g. 'pos_transactions'
    date_generated = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'reports'
        ordering = ['-date_generated']

    def __str__(self):
        return f'{self.get_report_type_display()} — {self.get_period_display()} ({self.date_generated:%Y-%m-%d})'
    
class Expense(models.Model):
    CATEGORY_CHOICES = [
        ('Utility', 'Utility (Kuryente, Tubig, Internet)'),
        ('Payroll', 'Payroll / Sweldo'),
        ('Rent', 'Rent / Upa'),
        ('Logistics', 'Delivery / Gasolina'),
        ('Supplies', 'Store Supplies'),
        ('Others', 'Others'),
    ]
    
    description = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Others')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    expense_date = models.DateField()
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} ({self.category}) - ₱{self.amount}"
