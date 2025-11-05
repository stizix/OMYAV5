from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from .models import CustomUser

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "password1", "password2")

class UsernameAuthenticationForm(AuthenticationForm):
    username = forms.CharField(label="Nom d'utilisateur", max_length=150)

    def confirm_login_allowed(self, user):
        # Optionally add custom login checks here
        pass 

# forms.py

from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["username", "email"]
        widgets = {
            "username": forms.TextInput(attrs={
                "class": "w-full px-3 py-2 rounded-xl border border-slate-200",
                "placeholder": "Username",
                "autocomplete": "username",
            }),
            "email": forms.EmailInput(attrs={
                "class": "w-full px-3 py-2 rounded-xl border border-slate-200",
                "placeholder": "Email",
                "autocomplete": "email",
            }),
        }

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Cet email est déjà utilisé.")
        return email
