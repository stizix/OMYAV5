from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, Permission
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)

    # ✅ Nouveaux compteurs séparés
    audio_credits_s = models.IntegerField(default=0)   # secondes audio
    text_credits_ch = models.IntegerField(default=0)   # caractères texte

    subscription = models.CharField(max_length=100, default="free")
    last_audio_reset = models.DateTimeField(default=timezone.now)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)

    # 🔧 Evite les conflits de reverse names avec AbstractUser
    groups = models.ManyToManyField(
        Group,
        related_name="customuser_groups",
        blank=True,
    )
    user_permissions = models.ManyToManyField(
        Permission,
        related_name="customuser_permissions",
        blank=True,
    )

    def __str__(self) -> str:
        return self.username

    # --------------------------
    # Quotas & reset mensuel
    # --------------------------
    def reset_monthly_credits(self) -> None:
        """
        Réinitialise les crédits 1 fois / ~30 jours en fonction de l'abonnement.
        """
        now = timezone.now()
        if self.last_audio_reset and (now - self.last_audio_reset) < timedelta(days=30):
            return

        quotas = {
            "free":    {"audio_s": 3 * 3600,  "text_ch": 50_000},
            "student": {"audio_s": 10 * 3600, "text_ch": 200_000},
            "pro":     {"audio_s": 20 * 3600, "text_ch": 500_000},
            "team":    {"audio_s": 40 * 3600, "text_ch": 1_000_000},
        }
        q = quotas.get(self.subscription, quotas["free"])
        self.audio_credits_s = q["audio_s"]
        self.text_credits_ch = q["text_ch"]
        self.last_audio_reset = now
        self.save(update_fields=["audio_credits_s", "text_credits_ch", "last_audio_reset"])

    # --------------------------
    # Helpers de vérification
    # --------------------------
    def has_enough_audio(self, seconds: int) -> bool:
        try:
            seconds = max(0, int(seconds))
        except Exception:
            return False
        return self.audio_credits_s >= seconds

    def has_enough_text(self, chars: int) -> bool:
        try:
            chars = max(0, int(chars))
        except Exception:
            return False
        return self.text_credits_ch >= chars

    # --------------------------
    # Débits atomiques anti-race
    # --------------------------
    @transaction.atomic
    def debit_audio(self, seconds: int) -> bool:
        seconds = max(0, int(seconds or 0))
        if seconds == 0:
            return True
        updated = (
            self.__class__
            .objects
            .filter(pk=self.pk, audio_credits_s__gte=seconds)
            .update(audio_credits_s=F("audio_credits_s") - seconds)
        )
        if updated:
            self.refresh_from_db(fields=["audio_credits_s"])
            return True
        return False

    @transaction.atomic
    def debit_text(self, chars: int) -> bool:
        chars = max(0, int(chars or 0))
        if chars == 0:
            return True
        updated = (
            self.__class__
            .objects
            .filter(pk=self.pk, text_credits_ch__gte=chars)
            .update(text_credits_ch=F("text_credits_ch") - chars)
        )
        if updated:
            self.refresh_from_db(fields=["text_credits_ch"])
            return True
        return False

    # --------------------------
    # Infos d'abonnement (optionnel)
    # --------------------------
    @property
    def current_subscription(self) -> str:
        return self.subscription

    @property
    def is_subscribed(self) -> bool:
        return self.subscription != "free"

    def get_subscription_display_name(self) -> str:
        subscription_names = {
            "free": "Free",
            "student": "Student",
            "pro": "Pro",
            "team": "Team",
        }
        return subscription_names.get(self.subscription, "Unknown")
