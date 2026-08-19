from django.utils.deprecation import MiddlewareMixin


class NoCacheMiddleware(MiddlewareMixin):
    """
    Middleware to prevent caching of authenticated pages.
    This ensures the browser back button cannot access authenticated pages after logout.
    """

    def process_response(self, request, response):
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate, private"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response
