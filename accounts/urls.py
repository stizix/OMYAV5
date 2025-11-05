
from django.contrib import admin
from django.urls import path
from .views import signup, logout_view, home, CustomLoginView, account_page, settings_view,SettingsPasswordChangeView, export_data, request_account_deletion,legal_terms, legal_privacy, legal_refunds, legal_imprint, cancel_subscription, roadmap
urlpatterns = [
    path("signup/", signup, name="signup"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("", home),
    path("roadmap/", roadmap, name="roadmap"),
    path("profile/", account_page, name="account_page"),

    path("settings/", settings_view, name="settings"),
    path("settings/password/", SettingsPasswordChangeView.as_view(), name="settings_password"),
    path("settings/cancel/", cancel_subscription, name="cancel_subscription"),
    path("settings/export/", export_data, name="export_data"),
    path("settings/delete/", request_account_deletion, name="request_account_deletion"),

    path("legal/terms/", legal_terms, name="legal_terms"),
    path("legal/privacy/", legal_privacy, name="legal_privacy"),
    path("legal/refunds/", legal_refunds, name="legal_refunds"),
    path("legal/imprint/", legal_imprint, name="legal_imprint"),

]