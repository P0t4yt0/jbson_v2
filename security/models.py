import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from auditlog.registry import auditlog

def generate_recovery_key():
    raw_key = uuid.uuid4().hex[:16].upper()
    return f"{raw_key[:4]}-{raw_key[4:8]}-{raw_key[8:12]}-{raw_key[12:]}"

class UserManager(BaseUserManager):
    def create_user(self, username, password=None, role="employee", **extra_fields):
        if not username:
            raise ValueError("A username is required.")
        user = self.model(username=username, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, role="admin", **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    ROLE_ADMIN = "admin"
    ROLE_EMPLOYEE = "employee"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_EMPLOYEE, "Employee"),
    ]

    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_EMPLOYEE)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_created = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "security_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == self.ROLE_EMPLOYEE

    def get_full_name(self):
        return self.full_name or self.username

class ActivityLog(models.Model):
    ACTION_LOGIN = "LOGIN"
    ACTION_LOGOUT = "LOGOUT"
    ACTION_USER_CREATED = "USER_CREATED"
    ACTION_USER_MODIFIED = "USER_MODIFIED"

    ACTION_CHOICES = [
        (ACTION_LOGIN, "Login"),
        (ACTION_LOGOUT, "Logout"),
        (ACTION_USER_CREATED, "User Created"),
        (ACTION_USER_MODIFIED, "User Modified"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name="security_logs",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "security_activity_log"
        ordering = ["-timestamp"]
        verbose_name = "Activity Log"
        verbose_name_plural = "Activity Logs"
        default_permissions = ("view",)

    def __str__(self):
        user_str = self.user.username if self.user else "deleted-user"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {user_str} – {self.action}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("ActivityLog entries cannot be modified once created.")
        super().save(*args, **kwargs)


class EmployeeProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    recovery_key = models.CharField(max_length=19, default=generate_recovery_key, unique=True)
    reset_requested = models.BooleanField(default=False)
    reset_approved_by_admin = models.BooleanField(default=False)
    
    # --- DASHBOARD ---
    dashboard_access_approved = models.BooleanField(default=False)
    dashboard_access_expires_at = models.DateTimeField(null=True, blank=True)

    # --- INVENTORY ---
    inv_products_access_approved = models.BooleanField(default=False)
    inv_products_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    inv_categories_access_approved = models.BooleanField(default=False)
    inv_categories_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    inv_po_access_approved = models.BooleanField(default=False)
    inv_po_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    inv_barcode_access_approved = models.BooleanField(default=False)
    inv_barcode_access_expires_at = models.DateTimeField(null=True, blank=True)

    # --- SALES & TRANSACTIONS ---
    sales_checkout_access_approved = models.BooleanField(default=False)
    sales_checkout_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_sales_access_approved = models.BooleanField(default=False)
    sales_sales_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_invoices_access_approved = models.BooleanField(default=False)
    sales_invoices_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_return_access_approved = models.BooleanField(default=False)
    sales_return_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_trade_credit_access_approved = models.BooleanField(default=False)
    sales_trade_credit_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_quotations_access_approved = models.BooleanField(default=False)
    sales_quotations_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    sales_suppliers_access_approved = models.BooleanField(default=False)
    sales_suppliers_access_expires_at = models.DateTimeField(null=True, blank=True)

    # --- REPORTS & ANALYTICS ---
    reports_access_requested = models.BooleanField(default=False)
    reports_access_approved = models.BooleanField(default=False)
    reports_access_expires_at = models.DateTimeField(null=True, blank=True)

    # --- USER MANAGEMENT ---
    um_users_access_approved = models.BooleanField(default=False)
    um_users_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    um_activity_logs_access_approved = models.BooleanField(default=False)
    um_activity_logs_access_expires_at = models.DateTimeField(null=True, blank=True)

    # --- SETTINGS & MANUAL ---
    settings_access_requested = models.BooleanField(default=False)
    settings_access_approved = models.BooleanField(default=False)
    settings_access_expires_at = models.DateTimeField(null=True, blank=True)
    
    user_manual_access_approved = models.BooleanField(default=False)
    user_manual_access_expires_at = models.DateTimeField(null=True, blank=True)

    can_edit_product = models.BooleanField(default=False)
    can_delete_product = models.BooleanField(default=False)
    can_import_csv = models.BooleanField(default=False)

    can_add_category = models.BooleanField(default=False)
    can_edit_category = models.BooleanField(default=False)
    can_delete_category = models.BooleanField(default=False)

    can_add_customer = models.BooleanField(default=False)
    can_view_ledger = models.BooleanField(default=False)
    can_receive_payment = models.BooleanField(default=False)

    can_add_supplier = models.BooleanField(default=False)
    can_edit_supplier = models.BooleanField(default=False)
    can_archive_supplier = models.BooleanField(default=False)
    can_restore_supplier = models.BooleanField(default=False)

    
    class Meta:
        db_table = "security_employee_profile"
        verbose_name = "Employee Profile"
        verbose_name_plural = "Employee Profiles"

    def __str__(self):
        return f"Profile for {self.user.username}"

    # DRY Helper function para sa expiration checking
    def _is_valid(self, is_approved, expires_at):
        if not is_approved:
            return False
        if expires_at and timezone.now() > expires_at:
            return False
        return True

    # ==========================================
    # PROPERTIES PARA SA CONTEXT PROCESSORS
    # ==========================================
    
    @property
    def has_dashboard_access(self):
        return self._is_valid(self.dashboard_access_approved, self.dashboard_access_expires_at)

    @property
    def has_inv_products_access(self): 
        return self._is_valid(self.inv_products_access_approved, self.inv_products_access_expires_at)
        
    @property
    def has_inv_categories_access(self): 
        return self._is_valid(self.inv_categories_access_approved, self.inv_categories_access_expires_at)
        
    @property
    def has_inv_po_access(self): 
        return self._is_valid(self.inv_po_access_approved, self.inv_po_access_expires_at)
        
    @property
    def has_inv_barcode_access(self): 
        return self._is_valid(self.inv_barcode_access_approved, self.inv_barcode_access_expires_at)

    @property
    def has_sales_checkout_access(self): 
        return self._is_valid(self.sales_checkout_access_approved, self.sales_checkout_access_expires_at)
        
    @property
    def has_sales_sales_access(self): 
        return self._is_valid(self.sales_sales_access_approved, self.sales_sales_access_expires_at)
        
    @property
    def has_sales_invoices_access(self): 
        return self._is_valid(self.sales_invoices_access_approved, self.sales_invoices_access_expires_at)
        
    @property
    def has_sales_return_access(self): 
        return self._is_valid(self.sales_return_access_approved, self.sales_return_access_expires_at)
        
    @property
    def has_sales_trade_credit_access(self): 
        return self._is_valid(self.sales_trade_credit_access_approved, self.sales_trade_credit_access_expires_at)
        
    @property
    def has_sales_quotations_access(self): 
        return self._is_valid(self.sales_quotations_access_approved, self.sales_quotations_access_expires_at)
        
    @property
    def has_sales_suppliers_access(self): 
        return self._is_valid(self.sales_suppliers_access_approved, self.sales_suppliers_access_expires_at)

    @property
    def has_valid_reports_access(self): 
        return self._is_valid(self.reports_access_approved, self.reports_access_expires_at)

    @property
    def has_um_users_access(self): 
        return self._is_valid(self.um_users_access_approved, self.um_users_access_expires_at)
        
    @property
    def has_um_activity_logs_access(self): 
        return self._is_valid(self.um_activity_logs_access_approved, self.um_activity_logs_access_expires_at)

    @property
    def has_valid_settings_access(self): 
        return self._is_valid(self.settings_access_approved, self.settings_access_expires_at)
        
    @property
    def has_user_manual_access(self): 
        return self._is_valid(self.user_manual_access_approved, self.user_manual_access_expires_at)

auditlog.register(User, exclude_fields=['password', 'last_login'])