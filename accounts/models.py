from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user model, set via AUTH_USER_MODEL."""

    THEME_CHOICES = [
        ("light", "Light"),
        ("dark", "Dark"),
        ("system", "System"),
    ]

    PROFILE_VISIBILITY_CHOICES = [
        ("everyone", "Everyone"),
        ("contacts", "My Contacts"),
        ("nobody", "Nobody"),
    ]

    display_name = models.CharField(max_length=60, blank=True)
    bio = models.CharField(max_length=240, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    is_online = models.BooleanField(default=False)
    last_seen = models.DateTimeField(auto_now=True)
    theme = models.CharField(max_length=10, choices=THEME_CHOICES, default="system")

    # ---- Privacy settings (see accounts.views.privacy_setting) ----
    # Whether other users may see this user's online/last-seen state. When off,
    # every payload and presence frame reports the user as offline.
    show_online_status = models.BooleanField(default=True)
    # Whether reading someone's messages reveals a read receipt to that sender.
    # When off, the user's reads never surface to the other side.
    read_receipts = models.BooleanField(default=True)
    # Who may see this user's profile information (bio / email).
    profile_visibility = models.CharField(
        max_length=10, choices=PROFILE_VISIBILITY_CHOICES, default="everyone"
    )

    class Meta:
        ordering = ["username"]
        constraints = [
            models.UniqueConstraint(
                fields=["email"],
                condition=~models.Q(email=""),
                name="unique_email_when_set",
            ),
        ]

    def __str__(self):
        return self.display_name or self.username
