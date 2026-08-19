from django.contrib import admin
from django.db import models

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "participant_list", "message_count", "created_at", "updated_at")
    list_filter = ("created_at", "updated_at")
    search_fields = ("participants__username", "participants__display_name")
    filter_horizontal = ("participants",)
    inlines = (MessageInline,)
    date_hierarchy = "created_at"
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .prefetch_related("participants")
            .annotate(_message_count=models.Count("messages"))
        )

    @admin.display(description="Participants")
    def participant_list(self, obj):
        return ", ".join(u.username for u in obj.participants.all()[:3])

    @admin.display(description="Messages")
    def message_count(self, obj):
        return obj._message_count


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "sender", "preview", "is_read", "created_at")
    list_filter = ("is_read", "created_at")
    search_fields = ("content", "sender__username", "sender__display_name")
    autocomplete_fields = ("conversation", "sender")
    readonly_fields = ("created_at",)
    date_hierarchy = "created_at"
    list_select_related = ("conversation", "sender")

    @admin.display(description="Message")
    def preview(self, obj):
        text = obj.content.strip()
        return text[:60] if text else "[image]"
