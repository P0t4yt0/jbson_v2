
from django.db import models
from django.conf import settings
from django.utils import timezone


class ManualSection(models.Model):

    SECTION_TYPE_CHOICES = [
        ('guide',           'System Guide'),
        ('faq',             'FAQs'),
        ('troubleshooting', 'Troubleshooting Guide'),
    ]

    title        = models.CharField(max_length=200)
    section_type = models.CharField(max_length=20, choices=SECTION_TYPE_CHOICES, default='guide')
    order        = models.PositiveSmallIntegerField(default=0)  # Display order
    is_active    = models.BooleanField(default=True)
    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='manual_sections'
    )
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'manual_sections'
        ordering = ['order', 'title']

    def __str__(self):
        return f'{self.get_section_type_display()} — {self.title}'


class ManualArticle(models.Model):

    section      = models.ForeignKey(ManualSection, on_delete=models.CASCADE, related_name='articles')
    title        = models.CharField(max_length=200)
    content      = models.TextField()   # HTML content
    order        = models.PositiveSmallIntegerField(default=0)
    is_active    = models.BooleanField(default=True)
    created_by   = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='manual_articles'
    )
    date_created = models.DateTimeField(default=timezone.now)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'manual_articles'
        ordering = ['order', 'title']

    def __str__(self):
        return f'{self.section.title} → {self.title}'
