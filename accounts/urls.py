from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.SignUpView.as_view(), name="signup"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/autosave/", views.settings_autosave, name="settings_autosave"),
    path("settings/privacy/", views.privacy_setting, name="privacy_setting"),
    path("delete-account/", views.delete_account, name="delete_account"),
    path("theme/", views.theme_preference, name="theme_preference"),
]
