# subscriptions/models.py
from django.db import models
from django.utils import timezone
from accounts.models import CustomUser
from dateutil.relativedelta import relativedelta
from django.conf import settings

class Subscription(models.Model):
   # user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='subscriptions')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions'
    )
    customer_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_id = models.CharField(max_length=255, unique=True)
    product_name = models.CharField(max_length=32)
    price = models.IntegerField(default=0)
    interval = models.CharField(max_length=16, default="month")
    start_date = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'canceled_at']),
        ]

    @property
    def is_active(self):
        return self.canceled_at is None

    @property
    def tier(self):
        return {'student':1,'pro':2,'team':3}.get((self.product_name or '').lower(), 0)

    def __str__(self):
        return f"{self.user.username} - {self.product_name} ({'Active' if self.is_active else 'Inactive'})"

    def next_billing_date(self):
        if not self.is_active: return None
        now_dt = timezone.now()
        nxt = self.start_date
        if self.interval == 'month':
            while nxt <= now_dt: nxt += relativedelta(months=1)
            return nxt
        if self.interval == 'year':
            while nxt <= now_dt: nxt += relativedelta(years=1)
            return nxt
        return None
