from django.core.management.base import BaseCommand
from django.utils import timezone
from inventory.models import ProductBatch
from activity_log.utils import log_system_activity
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = 'Automatically checks for expired ProductBatches and updates their status.'

    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        
        expired_batches = ProductBatch.objects.filter(
            expiry_date__lte=today,
            status__in=['active', 'near_expiry']
        )

        count = expired_batches.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No expired batches were found for today.'))
            return

        system_user = User.objects.filter(is_superuser=True).first()

        for batch in expired_batches:
            old_qty = batch.quantity_on_hand
            batch.status = 'expired'
            batch.save() 

            self.stdout.write(self.style.WARNING(f'Batch {batch.batch_code} marked as expired.'))
            
            if system_user:
                log_system_activity(
                    user=system_user,
                    action="SYSTEM AUTO-EXPIRE",
                    description=f"System automatically removed {old_qty} expired stocks from Batch {batch.batch_code} ({batch.product.item_name})."
                )

        self.stdout.write(self.style.SUCCESS(f'Successfully updated {count} expired batches!'))