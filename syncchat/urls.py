"""Root URL configuration for SyncChat."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve

from core.views import error_404, error_500

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("chat/", include("chat.urls")),
    path("", include("core.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("static/<path:path>", serve, {"document_root": settings.STATIC_ROOT}),
        path("media/<path:path>", serve, {"document_root": settings.MEDIA_ROOT}),
    ]

handler404 = error_404
handler500 = error_500
