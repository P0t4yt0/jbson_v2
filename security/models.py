"""
Module 1 — Security
Custom User model with bcrypt hashing and two-level role-based access.
Roles: admin (full access) | employee (limited access)
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    def create_user(self, username, password=None, **extra_fields):
        if not username:
            raise ValueError('Username is required.')
        user = self.model(username=username.strip(), **extra_fields)
        user.set_password(password)  # bcrypt hash via PASSWORD_HASHERS in settings
        user.save(using=self._db)
        return user

    def create_superuser(self, username, password=None, **extra_fields):
        extra_fields.setdefault('role', 'admin')
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Central JBSON user.
    Passwords stored as bcrypt hashes (BCryptSHA256PasswordHasher).
    """
    ROLE_CHOICES = [
        ('admin',    'Administrator'),
        ('employee', 'Employee'),
    ]

    full_name    = models.CharField(max_length=150)
    username     = models.CharField(max_length=50, unique=True)
    role         = models.CharField(max_length=10, choices=ROLE_CHOICES, default='employee')
    is_active    = models.BooleanField(default=True)
    is_staff     = models.BooleanField(default=False)
    date_created = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD  = 'username'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        db_table = 'users'
        ordering = ['full_name']
        verbose_name        = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return f'{self.full_name} ({self.get_role_display()})'

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.full_name.split()[0] if self.full_name else self.username

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_employee(self):
        return self.role == 'employee'
