from django.contrib import admin
from .models import (Operation, Delivery, ImportBatch, SourceSheet, PartnerBalance, Activity,
                     DebtPayment, Counterparty, RecordChange, Workspace, WorkspaceMembership)


class AuditReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Operation)
class OperationAdmin(AuditReadOnlyAdmin):
    list_display = ['workspace', 'date', 'description', 'kind', 'amount', 'active']
    list_filter = ['kind', 'active']
    search_fields = ['description', 'partner']


@admin.register(Delivery)
class DeliveryAdmin(AuditReadOnlyAdmin):
    list_display = ['workspace', 'date', 'vehicle', 'partner', 'direction', 'clean_weight', 'amount']
    list_filter = ['direction', 'active']


for model in (ImportBatch, SourceSheet, PartnerBalance, Activity, DebtPayment, Counterparty, RecordChange):
    admin.site.register(model, AuditReadOnlyAdmin)
admin.site.register(Workspace)
admin.site.register(WorkspaceMembership)
admin.site.site_header = 'MetalFlow · Администрирование'
