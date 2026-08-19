from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return redirect("login")


def error_404(request, exception):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
