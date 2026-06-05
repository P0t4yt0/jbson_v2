from django.db import models
from django.conf import settings
from django.utils import timezone

class SearchLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL,
        null=True, 
        blank=True, 
        related_name='searches'
    )
    query_text = models.CharField(max_length=200)
    result_table = models.CharField(max_length=50, blank=True)
    result_count = models.PositiveIntegerField(default=0)
    date_searched = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'search_logs'
        ordering = ['-date_searched']
        indexes = [models.Index(fields=['query_text'])]

    def __str__(self):
        return f'"{self.query_text}" → {self.result_count} result(s) ({self.date_searched:%Y-%m-%d %H:%M})'