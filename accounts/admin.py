from django.contrib import admin
from .models import CustomUser

from django.contrib import admin
from .models import CustomUser

@admin.register(CustomUser)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ('id','username', 'email', 'subscription', 'audio_credits_s', 'text_credits_ch', 'last_audio_reset')
    list_filter = ('subscription',)
    search_fields = ('username', 'email')
    fields = ('username', 'email', 'subscription', 'audio_credits_s', 'text_credits_ch', 'last_audio_reset')