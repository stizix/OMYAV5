from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Subscription
from django.utils import timezone


def subscription_required(subscription_types=None):
    """
    Vérifie qu'un utilisateur a un abonnement actif.
    - Si subscription_types est None -> tout plan payant est accepté (student/pro/team)
    - Sinon -> l'utilisateur doit avoir un des plans listés
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')

            current_subscription = (getattr(request.user, "subscription", "free") or "free").lower()

            if subscription_types is None:
                if current_subscription == 'free':
                    messages.error(request, 'Cette fonctionnalité nécessite un abonnement payant.')
                    return redirect('subscription_view')  # CHANGED (plus vers payment_page)
            else:
                if current_subscription not in subscription_types:
                    allowed_plans = ', '.join(subscription_types).title()
                    messages.error(request, f'Cette fonctionnalité nécessite un abonnement {allowed_plans}.')
                    return redirect('subscription_view')  # CHANGED

            # Abonnement actif en base (canceled_at is null)
            active_subscription = Subscription.objects.filter(
                user=request.user,
                canceled_at__isnull=True
            ).first()

            if not active_subscription:
                messages.error(request, 'Votre abonnement n’est pas actif. Veuillez souscrire.')
                return redirect('subscription_view')  # CHANGED

            # ❌ Ton modèle n’a pas 'end_date'. Si tu veux bloquer après échéance,
            # utilise 'canceled_at' (déjà géré) ou calcule une "date de prochaine échéance".
            # Exemple si tu veux empêcher après la période :
            # next_due = active_subscription.next_billing_date()
            # (ne bloque pas ici : la facturation est gérée par Stripe + webhook)

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

def student_required(view_func):
    """Décorateur pour les fonctionnalités nécessitant un abonnement Student ou supérieur"""
    return subscription_required(['student', 'pro', 'team'])(view_func)

def pro_required(view_func):
    """Décorateur pour les fonctionnalités nécessitant un abonnement Pro ou supérieur"""
    return subscription_required(['pro', 'team'])(view_func)

def team_required(view_func):
    """Décorateur pour les fonctionnalités nécessitant un abonnement Team"""
    return subscription_required(['team'])(view_func)

def check_usage_limits(limit_type, max_usage):
    """
    Décorateur pour vérifier les limites d'usage
    
    Args:
        limit_type: Type de limite ('monthly_courses', 'file_size', etc.)
        max_usage: Limite maximale autorisée
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            
            current_subscription = request.user.subscription
            
            # Limites selon l'abonnement
            limits = {
                'free': {
                    'monthly_courses': 3,
                    'file_size_mb': 100,
                    'file_duration_hours': 0.5
                },
                'student': {
                    'monthly_courses': 25,
                    'file_size_mb': 200,
                    'file_duration_hours': 2
                },
                'pro': {
                    'monthly_courses': 100,
                    'file_size_mb': 400,
                    'file_duration_hours': 4
                },
                'team': {
                    'monthly_courses': float('inf'),
                    'file_size_mb': 800,
                    'file_duration_hours': 8
                }
            }
            
            # Vérifier la limite
            if limit_type in limits[current_subscription]:
                current_limit = limits[current_subscription][limit_type]
                if current_limit < max_usage:
                    messages.error(request, f'Limite dépassée pour votre abonnement {current_subscription.title()}.')
                    return redirect('payment_page')
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

