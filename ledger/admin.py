from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import (Operation, Delivery, ImportBatch, SourceSheet, PartnerBalance, Activity,
                     DebtPayment, Counterparty, RecordChange, Workspace, WorkspaceMembership,
                     WorkspaceState)


User = get_user_model()


class WorkspaceCreateAdminForm(forms.ModelForm):
    owner_username = forms.CharField(
        label='Логин владельца', max_length=150,
        validators=User._meta.get_field('username').validators,
        help_text='С этим логином клиент войдёт в CRM.',
    )
    owner_password = forms.CharField(
        label='Пароль владельца', widget=forms.PasswordInput,
        help_text='Минимум 8 символов. Пароль сохраняется в защищённом виде.',
    )

    class Meta:
        model = Workspace
        fields = ['name', 'is_active']

    def clean_owner_username(self):
        username = self.cleaned_data['owner_username'].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError('Пользователь с таким логином уже существует.')
        return username

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('owner_password')
        username = cleaned.get('owner_username')
        if password and username:
            candidate = User(username=username)
            try:
                validate_password(password, candidate)
            except ValidationError as exc:
                self.add_error('owner_password', exc)
        return cleaned


class WorkspaceChangeAdminForm(forms.ModelForm):
    class Meta:
        model = Workspace
        fields = ['name', 'is_active']


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


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active', 'owner_logins', 'created_at']
    list_editable = ['is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'memberships__user__username']
    actions = ['activate_companies', 'suspend_companies']

    def get_form(self, request, obj=None, **kwargs):
        kwargs['form'] = WorkspaceChangeAdminForm if obj else WorkspaceCreateAdminForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            user = User.objects.create_user(
                username=form.cleaned_data['owner_username'],
                password=form.cleaned_data['owner_password'],
            )
            WorkspaceMembership.objects.create(
                workspace=obj,
                user=user,
                role=WorkspaceMembership.Role.OWNER,
            )
            WorkspaceState.objects.get_or_create(workspace=obj)

    @admin.display(description='Логины')
    def owner_logins(self, obj):
        return ', '.join(obj.memberships.values_list('user__username', flat=True)[:5]) or '—'

    @admin.action(description='Активировать выбранные компании')
    def activate_companies(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'Активировано компаний: {count}.')

    @admin.action(description='Приостановить выбранные компании')
    def suspend_companies(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'Приостановлено компаний: {count}.')


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ['user', 'workspace', 'role', 'created_at']
    list_filter = ['role', 'workspace']
    search_fields = ['user__username', 'workspace__name']


admin.site.site_header = 'MetalFlow · Администрирование'
