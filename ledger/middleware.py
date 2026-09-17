from django.contrib.auth.views import redirect_to_login
from django.urls import reverse

from .models import Workspace, WorkspaceMembership, WorkspaceState


class WorkspaceAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        public_paths = {reverse('login'), reverse('register'), reverse('set_language')}
        if (not request.user.is_authenticated
                and request.path not in public_paths
                and not request.path_info.startswith('/static/')):
            return redirect_to_login(request.get_full_path())
        if request.user.is_authenticated:
            membership = WorkspaceMembership.objects.select_related('workspace').filter(user=request.user).first()
            if membership is None:
                # Users created outside the sign-up form must receive an empty
                # company of their own, never another customer's workspace.
                workspace = Workspace.objects.create(name=request.user.get_username() or 'MetalFlow')
                WorkspaceState.objects.create(workspace=workspace)
                membership = WorkspaceMembership.objects.create(user=request.user, workspace=workspace)
            request.workspace = membership.workspace
            request.workspace_membership = membership
        return self.get_response(request)
