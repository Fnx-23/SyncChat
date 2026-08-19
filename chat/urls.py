from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("users/", views.SearchUsersView.as_view(), name="search_users"),
    path("start/", views.StartConversationView.as_view(), name="start_conversation"),
    path(
        "conversations/<int:pk>/read/",
        views.MarkConversationReadView.as_view(),
        name="conversation_read",
    ),
    path(
        "conversations/<int:pk>/mute/",
        views.ToggleMuteView.as_view(),
        name="conversation_mute",
    ),
    path(
        "users/<int:user_id>/block/",
        views.BlockUserView.as_view(),
        name="block_user",
    ),
    path(
        "users/<int:user_id>/unblock/",
        views.UnblockUserView.as_view(),
        name="unblock_user",
    ),
    path(
        "users/<int:user_id>/block-status/",
        views.BlockStatusView.as_view(),
        name="block_status",
    ),
    path(
        "blocked-users/",
        views.BlockedUsersView.as_view(),
        name="blocked_users",
    ),
    path(
        "conversations/<int:pk>/delete/",
        views.DeleteConversationView.as_view(),
        name="conversation_delete",
    ),
    path(
        "conversations/<int:pk>/messages/",
        views.SendMessageView.as_view(),
        name="conversation_send",
    ),
    path(
        "conversations/<int:pk>/history/",
        views.ConversationMessagesView.as_view(),
        name="conversation_history",
    ),
    path(
        "conversations/<int:pk>/detail/",
        views.ConversationDetailView.as_view(),
        name="conversation_detail",
    ),
    path("search/", views.SearchConversationsView.as_view(), name="search_conversations"),
    path(
        "conversations/<int:pk>/search/",
        views.SearchMessagesView.as_view(),
        name="conversation_search",
    ),
]
