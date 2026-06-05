from django.apps import AppConfig
import os


class BillingPaymentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing_payment'

    def ready(self):
        if os.environ.get('RUN_MAIN') == 'true':
            from . import updater
            updater.start()
