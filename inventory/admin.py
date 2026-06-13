from django.contrib import admin
from . import models
from .models import ProductBatch

@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = ('batch_code', 'product', 'quantity_on_hand', 'expiry_date', 'status')
    list_filter = ('status', 'expiry_date')
    search_fields = ('batch_code', 'product__item_name')

for model_name in dir(models):
    model = getattr(models, model_name)
    try:
        if hasattr(model, '_meta') and not model._meta.abstract:
            if not admin.site.is_registered(model):
                admin.site.register(model)
    except Exception:
        pass