from django.conf import settings
from django.contrib.auth.views import redirect_to_login


class WorkspaceAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        local = settings.LOCAL_WORKSPACE and request.META.get('REMOTE_ADDR') in ('127.0.0.1', '::1')
        if not local and not request.user.is_authenticated and not (request.path.startswith(('/login/', '/static/')) or request.path == '/i18n/setlang/'):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)
