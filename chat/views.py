from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Window
from django.db.models.functions import RowNumber
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django_ratelimit.decorators import ratelimit

from core.images import validate_image

from .broadcast import build_message_event, broadcast_new_message_notification
from .models import MAX_MESSAGE_LENGTH, Block, Conversation, Message, blocks_exist

MAX_SEARCH_QUERY = 100
DASHBOARD_MESSAGE_LIMIT = 50
MESSAGE_HISTORY_LIMIT = 50
MEDIA_GRID_LIMIT = 12


def _time_label(dt):
    """Format a timestamp as a short sidebar/history label (time, weekday, or date)."""
    if dt is None:
        return ""
    now = timezone.localtime()
    local = timezone.localtime(dt)
    today = now.date()
    if local.date() == today:
        return local.strftime("%I:%M %p").lstrip("0")
    if local.date() == today - timedelta(days=1):
        return "Yesterday"
    if today - local.date() < timedelta(days=7):
        return local.strftime("%a")
    return local.strftime("%b %d")


def _pair_key(uid_a, uid_b):
    return f"{min(int(uid_a), int(uid_b))}:{max(int(uid_a), int(uid_b))}"


def _other_in(conversation, ids):
    """True if the conversation's non-``me`` participant is in ``ids``."""
    return any(p.id in ids for p in conversation.participants.all())


def _muted_exists(user):
    """Exists subquery: whether ``user`` has muted the conversation."""
    return Exists(
        Conversation.muted_by.through.objects.filter(
            conversation_id=OuterRef("pk"),
            user_id=user.id,
        )
    )


def _blocked_user_ids(user):
    """Ids of the users ``user`` has blocked."""
    return set(Block.objects.filter(blocker=user).values_list("blocked_id", flat=True))


def _find_conversation(user, other):
    """The shared 1:1 conversation between ``user`` and ``other``, if any."""
    conversation = Conversation.objects.filter(
        pair_key=_pair_key(user.id, other.id)
    ).first()
    if conversation is None:
        # Fall back to a participant lookup for legacy conversations without a
        # pair key.
        conversation = (
            Conversation.objects.filter(participants=user)
            .filter(participants=other)
            .order_by("-updated_at")
            .first()
        )
    return conversation


def _broadcast_block_change(user, other):
    """Tell any shared conversation group that a block relationship changed.

    Both participants receive the frame; each side re-fetches the conversation
    and the server returns the correct per-requester view (anonymized or full),
    so blockers and blocked users both update in real time.
    """
    conversation = _find_conversation(user, other)
    if conversation is None:
        return
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"conversation_{conversation.id}",
        {
            "type": "chat.block_change",
            "conversation_id": conversation.id,
        },
    )


def _visible_messages_filter(user, prefix="messages"):
    """Q filter for the messages ``user`` is allowed to see.

    Messages saved with ``blocked_delivery=True`` were sent by the other
    participant while they were blocked, so they are hidden from the receiver.
    ``prefix`` is the join path ("messages" inside an annotate on Conversation,
    "" when filtering a Message queryset directly).
    """
    p = f"{prefix}__" if prefix else ""
    return Q(**{f"{p}sender": user}) | Q(**{f"{p}blocked_delivery": False})


def _deleted_conversation_ids(user):
    """Ids of conversations ``user`` has soft-deleted."""
    return set(user.deleted_conversations.values_list("id", flat=True))


def _is_hidden_conversation(conversation, user, blocked_ids=None):
    """True when the conversation's other participant is blocked by ``user``."""
    if blocked_ids is None:
        blocked_ids = _blocked_user_ids(user)
    other = next((p for p in conversation.participants.all() if p.id != user.id), None)
    return other is not None and other.id in blocked_ids


def _share_conversation(user_a, user_b):
    """True when two users are "contacts": they share at least one conversation."""
    return (
        Conversation.objects.filter(participants=user_a)
        .filter(participants=user_b)
        .exists()
    )


def _profile_info_visible(target, viewer=None, are_contacts=None):
    """Whether ``target``'s profile info (bio / email) may be shown to ``viewer``.

    Honours the target's ``profile_visibility`` privacy setting. A user always
    sees their own info. ``are_contacts`` lets a caller that already knows the
    relationship (e.g. the two participants of a conversation) skip the
    shared-conversation lookup. Fails closed: an unknown viewer only sees
    profiles marked visible to "everyone".
    """
    if viewer is not None and viewer.id == target.id:
        return True
    visibility = getattr(target, "profile_visibility", "everyone")
    if visibility == "everyone":
        return True
    if visibility == "nobody":
        return False
    # "contacts"
    if viewer is None:
        return False
    if are_contacts is None:
        are_contacts = _share_conversation(target, viewer)
    return bool(are_contacts)


def _participant_payload(user, include_email=True, viewer=None, are_contacts=None):
    # Privacy: hide online/last-seen when the user disabled online status, and
    # hide bio/email when their profile visibility excludes this viewer.
    online_visible = getattr(user, "show_online_status", True)
    profile_visible = _profile_info_visible(user, viewer, are_contacts)
    payload = {
        "name": user.display_name or user.username,
        "handle": f"@{user.username}",
        "username": user.username,
        "online": user.is_online if online_visible else False,
        "bio": user.bio if profile_visible else "",
        "avatar": user.avatar.url if user.avatar else None,
        "last_seen": (
            user.last_seen.isoformat() if user.last_seen else None
        ) if online_visible else None,
    }
    if include_email:
        payload["email"] = user.email if profile_visible else ""
    return payload


def _me_payload(user):
    """The current user's own identity, so the client can render their avatar
    in the sidebar footer and update it in real time on profile changes."""
    return {
        "id": user.id,
        "name": user.display_name or user.username,
        "handle": f"@{user.username}",
        "username": user.username,
        "avatar": user.avatar.url if user.avatar else None,
    }


def _message_payload(message, me, receipts_visible=True):
    payload = {
        "id": message.id,
        "from": "me" if message.sender_id == me.id else "them",
        "text": message.content,
        "image": message.image.url if message.image else None,
        # Raw timestamp so the client can format times and date separators in
        # the browser's own timezone instead of the server's (UTC) labels.
        "created_at": message.created_at.isoformat(),
        "time": _time_label(message.created_at),
    }
    # A read receipt is only exposed to the sender when the reader (the other
    # participant) allows it. The unread state itself is still tracked; only
    # its visibility to the sender is gated here.
    if message.sender_id == me.id and receipts_visible:
        payload["read"] = bool(message.is_read)
    return payload


def _recent_messages_queryset(limit):
    """Messages ranked per conversation, limited to the newest ``limit`` rows.

    A row-number window is used instead of a sliced Prefetch queryset because
    Django refuses to apply the reverse-FK filter to a sliced queryset.
    """
    return (
        Message.objects.annotate(
            _recent_rank=Window(
                RowNumber(),
                partition_by=F("conversation_id"),
                order_by=F("created_at").desc(),
            )
        )
        .filter(_recent_rank__lte=limit)
        .order_by("-created_at")
    )


def _prefetched_messages(conversation):
    """Messages in chronological order from the capped Prefetch cache."""
    messages = list(conversation.messages.all())
    messages.reverse()
    return messages


def _conversation_payload(conversation, me, messages=None, message_limit=None):
    other = next((p for p in conversation.participants.all() if p.id != me.id), None)
    if messages is None:
        queryset = conversation.messages.order_by("-created_at")
        if message_limit is not None:
            queryset = queryset[:message_limit]
        messages = list(queryset)
        messages.reverse()

    # Hide blocked-delivery messages (sent by the other participant while they
    # were blocked) from the receiver's view. The sender still sees them.
    messages = [m for m in messages if not (m.blocked_delivery and m.sender_id != me.id)]

    last_message = messages[-1] if messages else None
    last_activity = last_message.created_at if last_message else conversation.created_at
    total = getattr(conversation, "total_count", None)
    if total is None:
        total = conversation.messages.filter(_visible_messages_filter(me, "")).count()

    # Check block status
    blocked_by_me = False
    blocked_me = False
    if other:
        blocked_by_me = Block.objects.filter(blocker=me, blocked=other).exists()
        blocked_me = Block.objects.filter(blocker=other, blocked=me).exists()

    payload = (
        # The two participants of a conversation are contacts by definition, so
        # profile info is visible unless the other party hid it from everyone.
        _participant_payload(other, viewer=me, are_contacts=True)
        if other
        else {
            "name": "Unknown",
            "handle": "",
            "online": False,
            "email": "",
            "bio": "",
            "avatar": None,
            "last_seen": None,
        }
    )

    # Privacy: when the other participant has blocked us, they are shown as an
    # anonymous "Unknown User". Their identity (username, avatar, status, last
    # seen, profile info), shared media, and the message history are all hidden
    # and never sent to this client.
    if blocked_me:
        payload.update(
            {
                "name": "Unknown User",
                "handle": "",
                "username": "",
                "online": False,
                "avatar": None,
                "bio": "",
                "email": "",
                "last_seen": None,
                "joined": None,
            }
        )
        messages = []
        last_message = None
        total = 0

    # Read receipts on sent messages are only revealed when the other
    # participant (the reader) has read receipts enabled.
    receipts_visible = bool(other and getattr(other, "read_receipts", True))

    payload.update(
        {
            "id": conversation.id,
            # The other participant's user id, used by the New Chat modal so a
            # "Recent" entry can create/open the conversation for the right user.
            # Hidden entirely when the other participant blocked us: their
            # identity must never be sent to this client.
            "userId": None if blocked_me else (other.id if other else None),
            "muted": getattr(conversation, "is_muted", False),
            "blockedByMe": blocked_by_me,
            "blockedMe": blocked_me,
            "mediaCount": 0 if blocked_me else getattr(conversation, "media_count", 0),
            "media": [] if blocked_me else [m.image.url for m in reversed(messages) if m.image][:MEDIA_GRID_LIMIT],
            "unread": 0 if blocked_me else getattr(conversation, "unread_count", 0),
            "ts": int(last_activity.timestamp()),
            "lastMessage": last_message.content if last_message else ("No messages yet" if not blocked_me else ""),
            "time": _time_label(last_activity),
            "hasMore": total > len(messages),
            "messages": [_message_payload(m, me, receipts_visible) for m in messages],
        }
    )
    return payload


def _with_conversation_data(queryset, user):
    """Attach the sidebar's message prefetch and per-conversation annotations.

    Shared by the dashboard and conversation search so both compute identical
    counts (total / unread / media) and mute state. The caller supplies the
    base filtering and the final ordering.
    """
    return queryset.prefetch_related(
        "participants",
        Prefetch(
            "messages",
            queryset=_recent_messages_queryset(DASHBOARD_MESSAGE_LIMIT),
        ),
    ).annotate(
        total_count=Count("messages", filter=_visible_messages_filter(user)),
        unread_count=Count(
            "messages",
            filter=Q(messages__is_read=False)
            & ~Q(messages__sender=user)
            & Q(messages__blocked_delivery=False),
        ),
        media_count=Count(
            "messages",
            filter=Q(messages__image__gt="")
            & _visible_messages_filter(user),
        ),
        is_muted=_muted_exists(user),
    )


@login_required
def dashboard(request):
    conversations = list(
        _with_conversation_data(
            Conversation.objects.filter(participants=request.user), request.user
        ).order_by("-updated_at")
    )
    # Only hide conversations that are soft-deleted, NOT blocked ones
    deleted_ids = _deleted_conversation_ids(request.user)
    visible = [c for c in conversations if c.id not in deleted_ids]
    # Conversations whose other participant has blocked the requester are
    # anonymized; their unread counts must not surface in the total either.
    my_blocker_ids = set(
        Block.objects.filter(blocked=request.user).values_list("blocker_id", flat=True)
    )
    unread_total = 0
    for c in visible:
        if c.unread_count and not _other_in(c, my_blocker_ids):
            unread_total += c.unread_count
    data = {
        "me": request.user.username,
        "me_profile": _me_payload(request.user),
        "unread_total": unread_total,
        "conversations": [
            _conversation_payload(c, request.user, messages=_prefetched_messages(c))
            for c in visible
        ],
    }
    return render(
        request,
        "chat/dashboard.html",
        {"conversations": visible, "conversations_data": data},
    )


class MarkConversationReadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        other = conversation.participants.exclude(id=request.user.id).first()
        # Privacy: a blocked user never marks the blocker's messages as read,
        # so the blocker can't infer that the blocked user opened the chat.
        if other and Block.objects.filter(blocker=other, blocked=request.user).exists():
            return JsonResponse({"ok": True, "cleared": 0})
        updated = (
            Message.objects.filter(conversation=conversation, is_read=False)
            .exclude(sender=request.user)
            .update(is_read=True)
        )
        # The unread state is always cleared (so the reader's own unread badge
        # clears), but the sender is only notified that the messages were read
        # when the reader has read receipts enabled.
        if updated and request.user.read_receipts:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f"conversation_{pk}",
                {
                    "type": "chat.read",
                    "conversation_id": pk,
                    "reader": request.user.username,
                },
            )
        return JsonResponse({"ok": True})


class ToggleMuteView(LoginRequiredMixin, View):
    """Toggle the current user's mute state for a conversation."""

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        muted = conversation.muted_by.filter(id=request.user.id).exists()
        if muted:
            conversation.muted_by.remove(request.user)
        else:
            conversation.muted_by.add(request.user)
        return JsonResponse({"ok": True, "muted": not muted})


class BlockUserView(LoginRequiredMixin, View):
    """Block a user. Idempotent — blocking someone already blocked is a no-op."""

    def post(self, request, user_id):
        User = get_user_model()
        other = get_object_or_404(User, id=user_id)
        if other.id == request.user.id:
            return JsonResponse({"error": "You cannot block yourself."}, status=400)
        Block.objects.get_or_create(blocker=request.user, blocked=other)
        # Push the new state to any open conversation so the blocked user's
        # view anonymizes in real time.
        _broadcast_block_change(request.user, other)
        return JsonResponse({"ok": True, "blocked": True})


class UnblockUserView(LoginRequiredMixin, View):
    """Unblock a user. Idempotent — unblocking someone not blocked is a no-op.

    Messages the newly-unblocked user sent while the block was active were
    stored with ``blocked_delivery=True`` and hidden from the receiver; unblock
    reveals them again so the full conversation history is restored.
    """

    def post(self, request, user_id):
        User = get_user_model()
        other = get_object_or_404(User, id=user_id)
        if other.id == request.user.id:
            return JsonResponse({"error": "Invalid request."}, status=400)
        Block.objects.filter(blocker=request.user, blocked=other).delete()
        conversation = _find_conversation(request.user, other)
        if conversation is not None:
            Message.objects.filter(
                conversation=conversation,
                sender=other,
                blocked_delivery=True,
            ).update(blocked_delivery=False)
        # Push the restored state so both sides re-render without a refresh.
        _broadcast_block_change(request.user, other)
        return JsonResponse({"ok": True, "blocked": False})


class BlockStatusView(LoginRequiredMixin, View):
    """Get the block relationship between the current user and another user."""

    def get(self, request, user_id):
        User = get_user_model()
        other = get_object_or_404(User, id=user_id)
        if other.id == request.user.id:
            return JsonResponse({"blockedByMe": False, "blockedMe": False})

        blocked_by_me = Block.objects.filter(blocker=request.user, blocked=other).exists()

        # Never reveal that the other user has blocked the requester.
        return JsonResponse({
            "blockedByMe": blocked_by_me,
            "blockedMe": False,
        })


class BlockedUsersView(LoginRequiredMixin, View):
    """Get list of users blocked by the current user."""

    def get(self, request):
        blocks = Block.objects.filter(blocker=request.user).select_related("blocked")
        users = [
            {
                **_participant_payload(block.blocked, include_email=False),
                "id": block.blocked.id,
                "blockedAt": block.created_at.isoformat(),
            }
            for block in blocks
        ]
        return JsonResponse({"users": users})


class DeleteConversationView(LoginRequiredMixin, View):
    """Soft-delete a conversation for the current user only.

    The conversation and its messages are kept; the user's view is hidden and
    a later message from either participant restores it.
    """

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        conversation.deleted_by.add(request.user)
        return JsonResponse({"ok": True, "deleted": True})


class ConversationMessagesView(LoginRequiredMixin, View):
    """Paginated history: return messages older than ``before``, newest first."""

    @method_decorator(ratelimit(key="user", rate="60/m", method="GET", block=False))
    def get(self, request, pk):
        if request.limited:
            return JsonResponse({"error": "Too many requests. Try again in a minute."}, status=429)
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        queryset = conversation.messages.filter(
            _visible_messages_filter(request.user, "")
        ).order_by("-created_at")
        before = request.GET.get("before")
        if before:
            try:
                queryset = queryset.filter(id__lt=int(before))
            except (TypeError, ValueError):
                return JsonResponse({"error": "Invalid before id."}, status=400)
        page = list(queryset[: MESSAGE_HISTORY_LIMIT + 1])
        has_more = len(page) > MESSAGE_HISTORY_LIMIT
        messages = page[:MESSAGE_HISTORY_LIMIT]
        messages.reverse()
        return JsonResponse(
            {
                "messages": [_message_payload(m, request.user) for m in messages],
                "has_more": has_more,
            }
        )


class ConversationDetailView(LoginRequiredMixin, View):
    """Fresh copy of a single conversation, with block state applied.

    Used by the frontend to re-render a conversation in real time when the
    block relationship changes (block/unblock) without a full page reload.
    """

    @method_decorator(ratelimit(key="user", rate="60/m", method="GET", block=False))
    def get(self, request, pk):
        if request.limited:
            return JsonResponse({"error": "Too many requests. Try again in a minute."}, status=429)
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        payload = _conversation_payload(
            conversation, request.user, message_limit=DASHBOARD_MESSAGE_LIMIT
        )
        return JsonResponse({"conversation": payload})


class SendMessageView(LoginRequiredMixin, View):
    """Store a message over HTTP and broadcast it to the conversation group.

    Privacy-focused blocking: a block in either direction freezes the
    conversation. No new messages are created or delivered — both sides get an
    HTTP 403. The blocker's composer is replaced in the UI, so this guard also
    catches forged requests from the blocked user.
    """

    @method_decorator(ratelimit(key="user", rate="30/m", method="POST", block=False))
    def post(self, request, pk):
        if request.limited:
            return JsonResponse(
                {"error": "You are sending messages too quickly. Slow down."},
                status=429,
            )
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        other = conversation.participants.exclude(id=request.user.id).first()

        if other and blocks_exist(request.user, other):
            if Block.objects.filter(blocker=request.user, blocked=other).exists():
                error = "You cannot send messages to a user you have blocked. Unblock them first."
            else:
                error = "You cannot message this user."
            return JsonResponse({"error": error}, status=403)

        content = (request.POST.get("content") or "").strip()
        image = request.FILES.get("image")
        if not content and not image:
            return JsonResponse({"error": "Message cannot be empty."}, status=400)
        if len(content) > MAX_MESSAGE_LENGTH:
            return JsonResponse(
                {"error": f"Message is too long. Maximum is {MAX_MESSAGE_LENGTH} characters."},
                status=400,
            )
        if image:
            error = validate_image(image)
            if error:
                return JsonResponse({"error": error}, status=400)

        message = Message.objects.create(
            conversation=conversation,
            sender=request.user,
            content=content,
            image=image,
        )
        conversation.register_new_message(message)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"conversation_{pk}", build_message_event(message)
        )
        broadcast_new_message_notification(request.user, pk)
        return JsonResponse({"ok": True, "message": _message_payload(message, request.user)})


class SearchUsersView(LoginRequiredMixin, View):
    @method_decorator(ratelimit(key="user", rate="60/m", method="GET", block=False))
    def get(self, request):
        if request.limited:
            return JsonResponse({"error": "Too many searches. Try again in a minute."}, status=429)

        if request.GET.get("suggested") == "1":
            # Everyone the user has no active (non-deleted) conversation with.
            active_partner_ids = set(
                Conversation.objects.filter(participants=request.user)
                .exclude(deleted_by=request.user)
                .values_list("participants__id", flat=True)
            )
            queryset = get_user_model().objects.exclude(
                id__in=active_partner_ids | {request.user.id}
            )
        else:
            q = request.GET.get("q", "").strip()[:MAX_SEARCH_QUERY]
            queryset = get_user_model().objects.exclude(id=request.user.id)
            if q:
                queryset = queryset.filter(
                    Q(username__icontains=q)
                    | Q(display_name__icontains=q)
                    | Q(email__icontains=q)
                )

        # Email is intentionally excluded from search results. Profile info and
        # online status honour each result user's own privacy settings relative
        # to the searcher.
        users = [
            {**_participant_payload(user, include_email=False, viewer=request.user), "id": user.id}
            for user in queryset.order_by("username")[:10]
        ]
        return JsonResponse({"users": users})


class SearchConversationsView(LoginRequiredMixin, View):
    """Search the user's conversations by participant name or message content."""

    @method_decorator(ratelimit(key="user", rate="60/m", method="GET", block=False))
    def get(self, request):
        if request.limited:
            return JsonResponse({"error": "Too many searches. Try again in a minute."}, status=429)
        q = request.GET.get("q", "").strip()[:MAX_SEARCH_QUERY]
        if not q:
            return JsonResponse({"conversations": []})
        conversations = _with_conversation_data(
            Conversation.objects.filter(participants=request.user)
            .filter(
                Q(participants__username__icontains=q)
                | Q(participants__display_name__icontains=q)
                | Q(messages__content__icontains=q)
            )
            .distinct(),
            request.user,
        ).order_by("-updated_at")[:20]
        blocked_ids = _blocked_user_ids(request.user)
        deleted_ids = _deleted_conversation_ids(request.user)
        return JsonResponse(
            {
                "conversations": [
                    _conversation_payload(c, request.user, messages=_prefetched_messages(c))
                    for c in conversations
                    if c.id not in deleted_ids
                    and not _is_hidden_conversation(c, request.user, blocked_ids)
                ]
            }
        )


class SearchMessagesView(LoginRequiredMixin, View):
    """Search messages within a conversation the user is part of."""

    @method_decorator(ratelimit(key="user", rate="60/m", method="GET", block=False))
    def get(self, request, pk):
        if request.limited:
            return JsonResponse({"error": "Too many searches. Try again in a minute."}, status=429)
        conversation = get_object_or_404(Conversation, id=pk, participants=request.user)
        q = request.GET.get("q", "").strip()[:MAX_SEARCH_QUERY]
        if not q:
            return JsonResponse({"messages": []})
        messages = conversation.messages.filter(
            _visible_messages_filter(request.user, ""),
            content__icontains=q,
        )[:50]
        return JsonResponse({"messages": [_message_payload(m, request.user) for m in messages]})


class StartConversationView(LoginRequiredMixin, View):
    @method_decorator(ratelimit(key="user", rate="20/m", method="POST", block=False))
    def post(self, request):
        if request.limited:
            return JsonResponse(
                {"error": "You are creating conversations too quickly."}, status=429
            )
        user_id = request.POST.get("user_id")
        if not user_id:
            return JsonResponse({"error": "user_id is required."}, status=400)
        User = get_user_model()
        try:
            other = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "User not found."}, status=404)
        except (TypeError, ValueError):
            return JsonResponse({"error": "Invalid user_id."}, status=400)
        if other.id == request.user.id:
            return JsonResponse(
                {"error": "You cannot start a conversation with yourself."},
                status=400,
            )
        if blocks_exist(request.user, other):
            return JsonResponse({"error": "You cannot message this user."}, status=403)

        conversation = self._find_or_create(request.user, other)
        return JsonResponse({"conversation": _conversation_payload(conversation, request.user)})

    def _find_or_create(self, me, other):
        pair_key = _pair_key(me.id, other.id)
        conversation = Conversation.objects.filter(pair_key=pair_key).first()
        if conversation is None:
            # Legacy fallback: reuse a 2-participant chat created before pair
            # keys were introduced (they are all backfilled by migration).
            candidates = Conversation.objects.filter(participants=me).filter(participants=other)
            conversation = next(
                (c for c in candidates if c.participants.count() == 2),
                None,
            )
        if conversation is None:
            try:
                conversation = Conversation.objects.create(pair_key=pair_key)
                conversation.participants.add(me, other)
            except IntegrityError:
                # A concurrent request created the same pair first.
                conversation = Conversation.objects.get(pair_key=pair_key)
        return conversation
