# jbson_v2/billing_payment/management/commands/check_invoices.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from billing_payment.models import Invoice
from notifications.models import Notification

class Command(BaseCommand):
    help = 'Awtomatikong nag-check ng mga due dates at nagpapadala ng notifications'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        target_3_days = today + timedelta(days=3)

        # 1. NOTIFICATION: 3 DAYS BEFORE DUE DATE
        invoices_3_days = Invoice.objects.filter(status='unpaid', due_date=target_3_days, balance_due__gt=0)
        for inv in invoices_3_days:
            title = f"Invoice {inv.invoice_no} Due in 3 Days"
            # I-check kung nagpadala na para hindi mag-spam
            if not Notification.objects.filter(source_id=inv.invoice_no, title=title).exists():
                Notification.objects.create(
                    notification_type='invoice_due',
                    priority='medium',
                    title=title,
                    message=f"Reminder: Invoice {inv.invoice_no} for {inv.customer.name} is due on {inv.due_date.strftime('%b %d, %Y')}. Remaining Balance: ₱{inv.balance_due}.",
                    source_table='invoices',
                    source_id=inv.invoice_no,
                    action_url='/billing/invoices/'  # <--- IDAGDAG ITO SA LAHAT NG TATLONG NOTIFICATION.OBJECTS.CREATE
                )
                self.stdout.write(f"Created 3-day reminder for {inv.invoice_no}")

        # 2. NOTIFICATION: EXACT DUE DATE (TODAY)
        invoices_today = Invoice.objects.filter(status='unpaid', due_date=today, balance_due__gt=0)
        for inv in invoices_today:
            title = f"Invoice {inv.invoice_no} is Due TODAY"
            if not Notification.objects.filter(source_id=inv.invoice_no, title=title).exists():
                Notification.objects.create(
                    notification_type='invoice_due',
                    priority='high',
                    title=title,
                    message=f"Action Required: Invoice {inv.invoice_no} for {inv.customer.name} is due today! Collect the balance of ₱{inv.balance_due}.",
                    source_table='invoices',
                    source_id=inv.invoice_no,
                    action_url='/billing/invoices/'
                )
                self.stdout.write(f"Created due today alert for {inv.invoice_no}")

        # 3. NOTIFICATION: OVERDUE (MISSED PAYMENT)
        invoices_overdue = Invoice.objects.filter(status='unpaid', due_date__lt=today, balance_due__gt=0)
        for inv in invoices_overdue:
            # Awtomatikong palitan ang status ng invoice to overdue
            inv.status = 'overdue'
            inv.save(update_fields=['status'])
            
            # Awtomatikong i-hold ang account ng customer
            if inv.customer:
                inv.customer.check_overdue_status()

            title = f"OVERDUE: Invoice {inv.invoice_no}"
            if not Notification.objects.filter(source_id=inv.invoice_no, title=title).exists():
                Notification.objects.create(
                    notification_type='invoice_overdue',
                    priority='critical',
                    title=title,
                    message=f"Critical: Invoice {inv.invoice_no} for {inv.customer.name} is overdue! The customer account is now restricted. Unpaid Balance: ₱{inv.balance_due}.",
                    source_table='invoices',
                    source_id=inv.invoice_no,
                    action_url='/billing/invoices/'
                )
                self.stdout.write(f"Created OVERDUE alert for {inv.invoice_no}")
        
        self.stdout.write(self.style.SUCCESS('Successfully checked all invoices and updated notifications.'))