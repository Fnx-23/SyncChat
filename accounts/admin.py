from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User as DefaultAuthUser

User = get_user_model()


class SyncChatUserAdmin(UserAdmin):
    list_display = ("username", "email", "display_name", "is_online", "last_seen")
    list_filter = ("is_online", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "display_name")

    fieldsets = UserAdmin.fieldsets + (
        ("Profile", {"fields": ("display_name", "bio", "avatar", "is_online")}),
    )


# Hide the unused default auth.User from the admin (it is auto-registered by
# django.contrib.auth.admin even when AUTH_USER_MODEL points elsewhere).
try:
    admin.site.unregister(DefaultAuthUser)
except NotRegistered:
    pass

admin.site.register(User, SyncChatUserAdmin)
