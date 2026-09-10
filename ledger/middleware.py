from django.contrib.auth.views import redirect_to_login
from django.urls import reverse


class WorkspaceAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_paths = {reverse('login'), reverse('set_language')}
        if (not request.user.is_authenticated
                and request.path not in public_paths
                and not request.path_info.startswith('/static/')):
            return redirect_to_login(request.get_full_path())
        return self.get_response(request)
