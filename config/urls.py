from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from ledger.forms import WorkspaceLoginForm

urlpatterns = [path('admin/', admin.site.urls),
               path('i18n/', include('django.conf.urls.i18n')),
               path('login/', auth_views.LoginView.as_view(template_name='registration/login.html', authentication_form=WorkspaceLoginForm), name='login'),
               path('logout/', auth_views.LogoutView.as_view(), name='logout'),
               path('', include('ledger.urls'))]
