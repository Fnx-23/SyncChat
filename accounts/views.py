from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods
from django.views.generic.edit import FormView
from django_ratelimit.decorators import ratelimit

from chat.broadcast import (
    broadcast_presence,
    broadcast_profile_update,
    build_presence_event,
)
from chat.models import Conversation

from .forms import LoginForm, PasswordChangeForm, SignUpForm, UserProfileForm


class SignUpView(FormView):
    template_name = "accounts/signup.html"
    form_class = SignUpForm
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    @method_decorator(ratelimit(key="ip", rate="5/m", method="POST", block=False))
    def post(self, request, *args, **kwargs):
        if request.limited:
            form = self.get_form()
            form.add_error(
                None,
                "Too many sign-up attempts from this address. Please wait a minute.",
            )
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        login(self.request, user)
        messages.success(
            self.request,
            f"Welcome to SyncChat, {user.display_name or user.username}!",
        )
        return super().form_valid(form)


class LoginView(LoginView):
    template_name = "accounts/login.html"
    form_class = LoginForm
    redirect_authenticated_user = True

    @method_decorator(ratelimit(key="ip", rate="10/m", method="POST", block=False))
    def post(self, request, *args, **kwargs):
        if request.limited:
            form = self.get_form()
            form.add_error(
                None,
                "Too many login attempts. Please wait a minute and try again.",
            )
            return self.form_invalid(form)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        messages.success(
            self.request,
            f"Welcome back, {user.display_name or user.username}!",
        )
        return super().form_valid(form)


class LogoutView(LogoutView):
    next_page = "login"
    # POST only: a GET logout would let any page force the user out via CSRF
    # (e.g. <img src="/accounts/logout/">). The UI submits a CSRF-protected form.
    http_method_names = ["post", "options"]

    def dispatch(self, request, *args, **kwargs):
        if request.method == "POST":
            # Presence is application-wide; going offline is immediate on
            # logout rather than waiting out the socket grace period.
            if request.user.is_authenticated:
                broadcast_presence(request.user, False)
            messages.success(request, "You have been logged out successfully.")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        # Explicitly block GET requests with a redirect
        return redirect("login")


@login_required
def settings_view(request):
    """Unified "Profile Settings" page.

    Renders and handles both halves of the page in one place: the Profile
    Information section (display name, username, email, bio, avatar via
    ``UserProfileForm``) and the Account Settings sections (password via
    ``PasswordChangeForm``; privacy toggles auto-save through
    ``privacy_setting``). There is no separate "My Profile" view — this is the
    single destination behind ``name="settings"``.
    """
    if request.method == "POST":
        if request.POST.get("form_type") == "password":
            password_form = PasswordChangeForm(request.user, request.POST)
            profile_form = UserProfileForm(instance=request.user)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Your password has been updated.")
                return redirect("settings")
        else:
            profile_form = UserProfileForm(request.POST, request.FILES, instance=request.user)
            password_form = PasswordChangeForm(request.user)
            if profile_form.is_valid():
                profile_form.save()
                # Push the new name/avatar to every connected client so no
                # refresh is needed anywhere.
                broadcast_profile_update(request.user)
                messages.success(request, "Your profile has been updated.")
                return redirect("settings")
    else:
        profile_form = UserProfileForm(instance=request.user)
        password_form = PasswordChangeForm(request.user)

    return render(
        request,
        "accounts/settings.html",
        {
            "profile_form": profile_form,
            "password_form": password_form,
        },
    )


@login_required
@require_http_methods(["POST"])
def settings_autosave(request):
    """AJAX endpoint for auto-saving individual profile fields."""
    field_name = request.POST.get("field")
    field_value = request.POST.get("value")

    allowed_fields = ["display_name", "username", "email", "bio"]
    if field_name not in allowed_fields:
        return JsonResponse({"success": False, "error": "Invalid field"}, status=400)

    data = {field_name: field_value}
    form = UserProfileForm(data, instance=request.user, partial=True)

    if form.is_valid():
        form.save()
        # Real-time name updates: other clients pick the change up from the
        # presence-group broadcast without a refresh.
        broadcast_profile_update(request.user)
        return JsonResponse({"success": True})
    else:
        errors = form.errors.get(field_name, ["Invalid value"])
        return JsonResponse({"success": False, "error": errors[0]}, status=400)


@require_http_methods(["POST"])
def theme_preference(request):
    """Save theme preference for authenticated users, return success for anonymous."""
    theme = request.POST.get("theme")

    if theme not in ["light", "dark", "system"]:
        return JsonResponse({"success": False, "error": "Invalid theme"}, status=400)

    if request.user.is_authenticated:
        request.user.theme = theme
        request.user.save(update_fields=["theme"])

    return JsonResponse({"success": True})


# Boolean privacy toggles and the accepted values for the choice field. The
# server is the single source of truth: the field name and its value are both
# validated here, and the change is only ever applied to request.user.
PRIVACY_BOOL_FIELDS = ("show_online_status", "read_receipts")
PRIVACY_VISIBILITY_VALUES = {"everyone", "contacts", "nobody"}


@login_required
@require_http_methods(["POST"])
def privacy_setting(request):
    """Persist a single privacy control for the authenticated user.

    Each control auto-saves on change. Only the logged-in user's own row is
    ever touched: there is no target-user parameter, so one account can never
    change another's settings. Values are validated server-side and untrusted
    input is rejected with 400.
    """
    field = request.POST.get("field")
    value = request.POST.get("value")

    if field in PRIVACY_BOOL_FIELDS:
        if value not in ("true", "false"):
            return JsonResponse({"success": False, "error": "Invalid value"}, status=400)
        setattr(request.user, field, value == "true")
    elif field == "profile_visibility":
        if value not in PRIVACY_VISIBILITY_VALUES:
            return JsonResponse({"success": False, "error": "Invalid value"}, status=400)
        request.user.profile_visibility = value
    else:
        return JsonResponse({"success": False, "error": "Invalid field"}, status=400)

    request.user.save(update_fields=[field])
    return JsonResponse({"success": True})


def _announce_offline(user):
    """Push an offline presence frame for a user that is about to be deleted.

    Unlike broadcast_presence this never touches the database (the row is on
    its way out), it only notifies still-connected clients.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        "presence",
        build_presence_event(user, False),
    )


def _delete_account_data(user):
    """Delete ``user`` and everything that belongs only to them.

    Model relationships are honoured so no broken foreign keys or orphans are
    left behind:
      * The user's sent messages and their block rows (both directions) are
        removed by the ``on_delete=CASCADE`` foreign keys.
      * Conversation membership rows are dropped automatically with the user.
      * A conversation still shared with another (living) participant is kept
        intact, so the other person never loses their copy or their messages.
      * A conversation left with no participants at all is a true orphan and
        is removed.
      * The user's own uploaded files (avatar + message images) are deleted
        from storage so nothing dangles on disk.
    """
    conversation_ids = list(user.conversations.values_list("id", flat=True))

    # Capture the user's own media before the rows disappear, then delete the
    # files only after the database delete succeeds.
    media_files = [m.image for m in user.sent_messages.all() if m.image]
    if user.avatar:
        media_files.append(user.avatar)

    with transaction.atomic():
        user.delete()
        Conversation.objects.filter(id__in=conversation_ids).annotate(
            participant_count=Count("participants")
        ).filter(participant_count=0).delete()

    for file in media_files:
        file.delete(save=False)


@login_required
@require_http_methods(["POST"])
def delete_account(request):
    """Permanently delete the currently authenticated user's own account.

    Requires an explicit confirmation and a correct password (re-auth). On
    success the session is flushed, connected clients are told the user went
    offline, and the client is redirected to the login page.
    """
    user = request.user
    password = request.POST.get("password", "")
    confirmed = request.POST.get("confirm") == "true"

    if not confirmed:
        return JsonResponse(
            {
                "success": False,
                "error": "Please confirm that you want to permanently delete your account.",
            },
            status=400,
        )

    if not password or not user.check_password(password):
        return JsonResponse(
            {
                "success": False,
                "error": "Incorrect password. Your account was not deleted.",
            },
            status=400,
        )

    _announce_offline(user)
    _delete_account_data(user)

    # Invalidate the session so the now-deleted account cannot keep using it.
    logout(request)
    messages.success(request, "Your account has been permanently deleted.")

    return JsonResponse({"success": True, "redirect": reverse("login")})
