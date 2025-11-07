# subscriptions/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path("create-checkout-session-hosted/", views.create_checkout_session_hosted, name="create_checkout_session_hosted"),
    path("webhook/", views.stripe_webhook, name="stripe_webhook"),
    path("success/", views.payment_success, name="payment_success"),
    path("cancel/", views.payment_cancel, name="payment_cancel"),
    path("check-status/", views.check_status, name="subscription_check_status"),
    path("my/", views.my_sub_view, name="my_sub"),
    path("reset-credits/", views.reset_credits_view, name="reset_credits"),

]
