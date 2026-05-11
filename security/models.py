"""
security/models.py
─────────────────────────────────────────────────────────────────────────────
Security Module – Database Models
Product Management System with POS for JBSON Hardware

Models:
  - User         Custom user model with username + bcrypt password + role field
  - ActivityLog  Immutable audit trail (login/logout/create/modify events)
─────────────────────────────────────────────────────────────────────────────
"""

from auditlog.registry import auditlog
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# Custom User Manager
# ─────────────────────────────────────────────────────────────────────────────

class UserManager(BaseUserManager):
    """Manager for the custom User model."""

    def create_user(self, username, password=None, role="employee", **extra_fields):
        if not username:
            raise ValueError("A username is required.")
        user = self.model(username=username, role=role, **extra_fields)
        # set_password() calls Django's PASSWORD_HASHERS → bcrypt (first in list)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(username, password, role="admin", **extra_fields)


# ─────────────────────────────────────────────────────────────────────────────
# Custom User Model
# ─────────────────────────────────────────────────────────────────────────────

class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model.

    Stores a bcrypt-hashed password (Django's hasher infrastructure).
    The `role` field drives all access-control decisions:
        'admin'    → Administrator  – full system privileges
        'employee' → Employee       – restricted to POS / Billing / Inventory
    """

    ROLE_ADMIN = "admin"
    ROLE_EMPLOYEE = "employee"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_EMPLOYEE, "Employee"),
    ]

    # Core identity fields
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_EMPLOYEE)

    # Account state
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access

    date_created = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = []  # username + password are always required

    class Meta:
        db_table = "security_user"
        verbose_name = "User"
        verbose_name_plural = "Users"

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def is_admin(self) -> bool:
        return self.role == self.ROLE_ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == self.ROLE_EMPLOYEE

    def get_full_name(self):
        return self.full_name or self.username


# ─────────────────────────────────────────────────────────────────────────────
# Activity Log  (immutable audit trail)
# ─────────────────────────────────────────────────────────────────────────────

class ActivityLog(models.Model):
    """
    Immutable audit record for all significant user actions.

    Per project spec:
      - Administrators can VIEW logs but not modify them.
      - Automatic logging is triggered from views/signals.
    """

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
        # Prevent updates via the ORM (delete is still possible for admins)
        default_permissions = ("view",)

    def __str__(self):
        user_str = self.user.username if self.user else "deleted-user"
        return f"[{self.timestamp:%Y-%m-%d %H:%M}] {user_str} – {self.action}"

    def save(self, *args, **kwargs):
        """Enforce immutability: only allow INSERTs."""
        if self.pk is not None:
            raise PermissionError("ActivityLog entries cannot be modified once created.")
        super().save(*args, **kwargs)
# ─────────────────────────────────────────────────────────────────────────────
# Employee Profile (Recovery System)
# ─────────────────────────────────────────────────────────────────────────────
import uuid

def generate_recovery_key():
    """
    Generates a 16-character alphanumeric key formatted as XXXX-XXXX-XXXX-XXXX.
    This is called when a new profile is created.
    """
    # Generate a random UUID, remove hyphens, make it uppercase, take first 16 chars
    raw_key = uuid.uuid4().hex[:16].upper()
    # Format it with hyphens for readability
    return f"{raw_key[:4]}-{raw_key[4:8]}-{raw_key[8:12]}-{raw_key[12:]}"

class EmployeeProfile(models.Model):
    """
    Extended profile for users, specifically handling the offline 
    account recovery system (Recovery Key & Admin Approval).
    """
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name="profile"
    )
    
    # The 16-character key (e.g. ABCD-1234-EFGH-5678)
    # Using default=generate_recovery_key ensures a key is made automatically
    recovery_key = models.CharField(
        max_length=19, 
        default=generate_recovery_key, 
        unique=True
    )
    
    # State tracking for the password reset flow
    reset_requested = models.BooleanField(default=False)
    reset_approved_by_admin = models.BooleanField(default=False)

    class Meta:
        db_table = "security_employee_profile"
        verbose_name = "Employee Profile"
        verbose_name_plural = "Employee Profiles"

    def __str__(self):
        return f"Profile for {self.user.username}"
    
auditlog.register(User, exclude_fields=['password', 'last_login'])
