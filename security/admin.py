from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display  = ['username', 'full_name', 'role', 'is_active', 'date_created']
    list_filter   = ['role', 'is_active']
    search_fields = ['username', 'full_name']
    ordering      = ['full_name']
    fieldsets = (
        (None,            {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('full_name',)}),
        ('Role & Access', {'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps',    {'fields': ('date_created', 'last_login')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('username', 'full_name', 'role', 'password1', 'password2')}),
    )
    readonly_fields = ['date_created', 'last_login']
