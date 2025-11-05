from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.views import LoginView
from .forms import CustomUserCreationForm, UsernameAuthenticationForm
from django.contrib.auth import login as auth_login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login as auth_login, authenticate
from django.contrib.auth import logout
from courses.models import Course 
from django.urls import reverse_lazy
from django.contrib.auth.views import PasswordChangeView
from .forms import UserSettingsForm
from django.contrib import messages
import stripe 
from subscriptions.models import Subscription
from allauth.account.adapter import get_adapter
from django.conf import settings
# add this import (and remove the broken one)
from allauth.account.models import EmailAddress


def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)

            # Ensure username exists if you disable usernames
            if not settings.ACCOUNT_USERNAME_REQUIRED and not user.username:
                user.username = get_adapter().generate_unique_username([user.email])

            user.is_active = True  # allauth will still block login until email is verified
            user.save()

            # ✅ Create EmailAddress and send confirmation in one go
            EmailAddress.objects.add_email(
                request,
                user,
                user.email,
                confirm=True,   # sends the verification email
                signup=True,    # marks flow as signup for templates/logic
            )

            messages.success(
                request,
                "We sent you a verification link. Check your inbox to activate your account."
            )
            return redirect('login')
    else:
        form = CustomUserCreationForm()
    return render(request, 'signup.html', {'form': form})

# Login view using email
class CustomLoginView(LoginView):
    authentication_form = UsernameAuthenticationForm
    template_name = 'login.html'

    def form_valid(self, form):
        user = form.get_user()
        email_verified = EmailAddress.objects.filter(user=user, verified=True).exists()
        if not email_verified:
            messages.error(self.request, "Please verify your email before logging in.")
            return redirect('login')
        return super().form_valid(form)
# Logout view
def logout_view(request):
    if request.method == 'POST':
        logout(request)
        return redirect('login')
def home(request) : 
    return render(request,'home.html')

def roadmap(request):
    return render(request, 'roadmap.html')

@login_required
def account_page(request):
    user = request.user

    # Réinitialiser les crédits si nécessaire
    user.reset_monthly_credits()

    # Obtenir le quota total en fonction de l'abonnement
    quotas = {
        'free': 3 * 3600,  # 3 heures en secondes
        'student': 10 * 3600,  # 10 heures en secondes
        'pro': 20 * 3600,  # 20 heures en secondes
    }
    quota = quotas.get(user.subscription, quotas['free'])

    # Calculer les crédits restants
    remaining_seconds = user.audio_credits_s
    remaining_hours = int(remaining_seconds // 3600)
    remaining_minutes = int((remaining_seconds % 3600) // 60)

    # Récupérer les cours de l'utilisateur
    courses = Course.objects.filter(user=user).order_by('-created_at')

    return render(request, 'account.html', {
        'user': user,
        'courses': courses,
        'remaining_hours': remaining_hours,
        'remaining_minutes': remaining_minutes,
        'quota': quota,
    })


@login_required
def settings_view(request):
    user = request.user
    if request.method == "POST":
        form = UserSettingsForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "Paramètres mis à jour ✅")
            return redirect("settings")
        else:
            messages.error(request, "Merci de corriger les erreurs ci-dessous.")
    else:
        form = UserSettingsForm(instance=user)

    ctx = {
        "form": form,
        "subscription": user.subscription,
        "credits audio": user.audio_credits_s,
        "credit texte" : user.text_credits_ch , 
        "last_audio_reset": user.last_audio_reset,
    }
    return render(request, "settings.html", ctx)


class SettingsPasswordChangeView(PasswordChangeView):
    template_name = "settings_change_password.html"  # simple page (optionnelle)
    success_url = reverse_lazy("settings")

    def form_valid(self, form):
        messages.success(self.request, "Mot de passe modifié ✅")
        return super().form_valid(form)
    

@login_required
def export_data(request):
    if request.method == "POST":
        # TODO: génère un ZIP, envoie un e-mail ou un lien de téléchargement
        messages.success(request, "Votre export sera prêt sous peu (fonctionnalité à venir).")
    return redirect("settings")

@login_required
def request_account_deletion(request):
    if request.method == "POST":
        # TODO: queue un job / envoie un e-mail de confirmation
        messages.success(request, "Votre demande de suppression a été enregistrée (fonctionnalité à venir).")
    return redirect("settings")

# ---------- LEGAL PAGES ----------
@login_required
def legal_terms(request):
    return render(request, "accounts/legal_terms.html")

@login_required
def legal_privacy(request):
    return render(request, "accounts/legal_privacy.html")

@login_required
def legal_refunds(request):
    return render(request, "accounts/legal_refunds.html")

@login_required
def legal_imprint(request):
    return render(request, "accounts/legal_imprint.html")


@login_required
def cancel_subscription(request):
    if request.method != "POST":
        messages.error(request, "Action non autorisée.")
        return redirect("settings")

    user = request.user

    # 1) récupérer l'abonnement actif dans ta DB
    db_sub = Subscription.objects.filter(user=user, canceled_at__isnull=True).order_by("-start_date").first()
    if not db_sub:
        messages.error(request, "Aucun abonnement actif trouvé.")
        return redirect("settings")

    # 2) annuler côté Stripe à la fin de la période en cours
    try:
        stripe.Subscription.modify(
            db_sub.subscription_id,
            cancel_at_period_end=True,
        )
    except stripe.error.InvalidRequestError as e:
        messages.error(request, f"Stripe error: {getattr(e, 'user_message', str(e))}")
        return redirect("settings")
    except Exception as e:
        messages.error(request, f"Erreur: {str(e)}")
        return redirect("settings")

    # 3) on ne modifie PAS encore la DB (on attend le webhook 'deleted')
    messages.success(
        request,
        "Votre abonnement sera annulé à la fin de la période en cours. Vous conserverez l’accès jusque là."
    )
    return redirect("settings")

