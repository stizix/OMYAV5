# subscriptions/views.py
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect, reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.admin.views.decorators import staff_member_required

import json
import stripe

from .models import Subscription
from .decorators import subscription_required

stripe.api_key = settings.STRIPE_SECRET_KEY
# Stripe Prices -> plan
SUBSCRIPTION_PRICES = {
    "student": "price_1RqU64LEbdBArTdnOEnKHVqR",
    "pro":     "price_1RqU6XLEbdBArTdnNB2vMF1O",
    "team":    "price_1RqU6yLEbdBArTdn9nP5Gzia",
}
PRICE_TO_PLAN = {v: k for k, v in SUBSCRIPTION_PRICES.items()}

# Credits quota per plan (seconds)
QUOTAS = {
    "free":    3 * 3600,
    "student": 10 * 3600,
    "pro":     20 * 3600,
    "team":    50 * 3600,
}

# ---------- Core apply: switch active sub + mirror to user ----------
def _activate_subscription(user, *, plan: str, sub_id: str, customer_id: str, price_eur: int, interval: str):
    """
    Atomically:
      - cancel any previous active sub for user (canceled_at = now)
      - create a new active Subscription row
      - mirror plan/credits on CustomUser with a DB-level update
    """
    User = get_user_model()
    now = timezone.now()

    with transaction.atomic():
        # lock & cancel previous
        (Subscription.objects
            .select_for_update()
            .filter(user=user, canceled_at__isnull=True)
            .update(canceled_at=now))

        # create new active
        sub = Subscription.objects.create(
            user=user,
            subscription_id=sub_id,
            customer_id=customer_id,
            product_name=plan,
            price=price_eur,
            interval=interval,
            canceled_at=None,  # actif
        )

        # mirror to user
        User.objects.filter(pk=user.pk).update(
            subscription=plan,
            credits=QUOTAS.get(plan, 0),
            last_audio_reset=now,
        )

    return sub

# ---------- Stripe success application ----------
def _apply_subscription_from_session(user, session_dict: dict):
    sub_id = session_dict.get("subscription")
    customer_id = session_dict.get("customer")
    if not sub_id:
        return

    subscription = stripe.Subscription.retrieve(
        sub_id,
        expand=["items.data.price.product", "default_payment_method"]
    )

    item = subscription["items"]["data"][0]
    price = item["price"]
    product = price["product"]

    # Plan resolution: metadata.plan_key → fallback to configured price map → 'free'
    plan = (product.get("metadata", {}) or {}).get("plan_key")
    if not plan:
        try:
            plan = PRICE_TO_PLAN.get(price.get("id")) or "free"
        except Exception:
            plan = "free"
    interval = (price.get("recurring") or {}).get("interval", "month")
    unit_amount = int(price.get("unit_amount", 0) / 100)

    # Use transactional helper to cancel previous subs and mirror plan/credits
    _activate_subscription(
        user,
        plan=plan,
        sub_id=sub_id,
        customer_id=customer_id or "",
        price_eur=unit_amount,
        interval=interval,
    )

# ---------- Views ----------
@login_required
def subscription_view(request):
    """
    Crée la session Stripe Checkout et redirige l’utilisateur vers Stripe.
    On n’a plus de 'payment page' locale : en GET on renvoie vers le profil.
    """
    if request.method != "POST":
        messages.info(request, "Choisis un plan puis valide l’abonnement.")
        return redirect("account_page")

    price_id = request.POST.get("price_id")
    if not price_id:
        messages.error(request, "Veuillez sélectionner un plan d'abonnement.")
        return redirect("account_page")

    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=request.build_absolute_uri(reverse("payment_success")) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("payment_cancel")),
            customer_email=request.user.email,
            metadata={"user_id": str(request.user.id)},  # pour le webhook & success
        )
        return redirect(checkout_session.url, code=303)
    except stripe.error.StripeError as e:
        messages.error(request, f"Erreur Stripe: {str(e)}")
        return redirect("account_page")
    except Exception as e:
        messages.error(request, f"Erreur inattendue: {str(e)}")
        return redirect("account_page")

@login_required
@subscription_required()
def my_sub_view(request):
    subs = Subscription.objects.filter(user=request.user).order_by("-start_date")
    current = subs.filter(canceled_at__isnull=True).first()
    return HttpResponse(f"Active: {bool(current)} / Total subs: {subs.count()}")  # minimal; adapte ton template si besoin

# ---------- Webhook ----------
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("[webhook] signature/parse error:", e)
        return HttpResponse(status=400)

    etype = event["type"]
    print(f"[webhook] received: {etype}")

    if etype == "checkout.session.completed":
        session = event["data"]["object"]
        _handle_checkout_session_completed(session)

    elif etype == "customer.subscription.updated":
        sub_obj = event["data"]["object"]
        _handle_subscription_updated(sub_obj)

    elif etype == "customer.subscription.deleted":
        sub_obj = event["data"]["object"]
        _handle_subscription_deleted(sub_obj)

    elif etype == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")
        db_sub = Subscription.objects.filter(subscription_id=sub_id, canceled_at__isnull=True).first()
        if db_sub:
            user = db_sub.user
            plan = (db_sub.product_name or "free").lower()
            User = get_user_model()
            User.objects.filter(pk=user.pk).update(
                credits=QUOTAS.get(plan, 0),
                last_audio_reset=timezone.now(),
            )
            print(f"[webhook] reset mensuel des crédits pour {user.username} ({plan})")
    elif etype == "invoice.payment_failed":
        invoice = event["data"]["object"]
        sub_id = invoice.get("subscription")
        Subscription.objects.filter(subscription_id=sub_id).update(status="past_due")
        # Optional: notify user / throttle features

    return HttpResponse(status=200)

# ---------- Handlers appelés par le webhook ----------
def _handle_checkout_session_completed(session_dict: dict) -> None:
    try:
        metadata = session_dict.get("metadata") or {}
        user_id = metadata.get("user_id") or session_dict.get("client_reference_id")
        if not user_id:
            print("[webhook] no user_id in session metadata/client_reference_id")
            return
        User = get_user_model()
        user = User.objects.filter(pk=user_id).first()
        if not user:
            print(f"[webhook] checkout.completed: user {user_id} introuvable")
            return
        _apply_subscription_from_session(user, session_dict)
    except Exception as e:
        print(f"[webhook] error in _handle_checkout_session_completed: {e}")

def _handle_subscription_updated(sub_obj):
    sub_id = sub_obj.get("id")
    fields = {
        "status": sub_obj.get("status"),
        "cancel_at_period_end": sub_obj.get("cancel_at_period_end", False),
        "current_period_start": sub_obj.get("current_period_start"),
        "current_period_end": sub_obj.get("current_period_end"),
        "canceled_at": timezone.now() if sub_obj.get("status") in ("canceled", "unpaid") else None,
    }
    Subscription.objects.filter(subscription_id=sub_id).update(**{k:v for k,v in fields.items() if v is not None})

def _handle_subscription_deleted(sub_obj):
    try:
        sub_id = sub_obj.get("id")
        if not sub_id:
            print("[webhook] deleted: missing sub id")
            return

        db_sub = Subscription.objects.filter(subscription_id=sub_id, canceled_at__isnull=True).first()
        if not db_sub:
            db_sub = Subscription.objects.filter(subscription_id=sub_id).first()

        if not db_sub:
            print(f"[webhook] deleted: sub {sub_id} introuvable en DB → vérifie l’enregistrement au checkout")
            return

        if not db_sub.canceled_at:
            now = timezone.now()
            db_sub.canceled_at = now
            db_sub.save(update_fields=["canceled_at"])

        User = get_user_model()
        User.objects.filter(pk=db_sub.user_id).update(
            subscription="free",
            credits=QUOTAS.get("free", 0),
            last_audio_reset=timezone.now(),
        )
        print(f"[webhook] subscription {sub_id} DELETED → canceled_at set, user downgraded")
    except Exception as e:
        print(f"[webhook] error in _handle_subscription_deleted: {e}")

# ---------- API: Checkout session depuis un bouton JS ----------
@login_required
@require_POST
def create_checkout_session_hosted(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"error": "Invalid JSON"}, status=400)

    plan = (data.get("plan") or "").lower().strip()
    price_id = SUBSCRIPTION_PRICES.get(plan)
    if not price_id:
        return JsonResponse({"error": "Unknown plan"}, status=400)

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=request.build_absolute_uri(reverse("payment_success")) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.build_absolute_uri(reverse("payment_cancel")),
            customer_email=request.user.email,
            metadata={"user_id": str(request.user.id), "plan": plan},
        )
        return JsonResponse({"url": session.url}, status=200)
    except stripe.error.StripeError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": f"Unexpected error: {e}"}, status=500)

@login_required
def check_status(request):
    return JsonResponse({"subscription": getattr(request.user, "subscription", "free")})

@staff_member_required
def reset_credits_view(request):
    user = request.user
    plan = getattr(user, "subscription", "free")
    User = get_user_model()
    User.objects.filter(pk=user.pk).update(
        credits=QUOTAS.get(plan, 0),
        last_audio_reset=timezone.now(),
    )
    return HttpResponse("Credits reset OK")

# ---------- Success / Cancel (pas de templates requis) ----------
@login_required
def payment_success(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        messages.error(request, "Session Stripe manquante.")
        return redirect("account_page")

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.get("payment_status") == "paid":
            _apply_subscription_from_session(request.user, session)
            messages.success(request, "Votre abonnement a été activé 🎉")
            return redirect("account_page")
        else:
            messages.error(request, "Le paiement n'a pas été confirmé.")
            return redirect("account_page")
    except Exception as e:
        messages.error(request, f"Erreur: {e}")
        return redirect("account_page")

@login_required
def payment_cancel(request):
    messages.info(request, "Le paiement a été annulé ❌")
    return redirect("account_page")
