from django.contrib import admin
from .models import Operation, Delivery, ImportBatch, SourceSheet, PartnerBalance, Activity


@admin.register(Operation)
class OperationAdmin(admin.ModelAdmin):
    list_display = ['date', 'description', 'kind', 'amount', 'active']
    list_filter = ['kind', 'active']
    search_fields = ['description', 'partner']


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ['date', 'vehicle', 'partner', 'direction', 'clean_weight', 'amount']
    list_filter = ['direction', 'active']


for model in (ImportBatch, SourceSheet, PartnerBalance, Activity):
    admin.site.register(model)
admin.site.site_header = 'MetalFlow · Администрирование'
