"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from rest_framework_simplejwt.views import TokenRefreshView
from api.telegram_auth import TelegramAuthView, LinkAccountView, RegisterView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/telegram/', TelegramAuthView.as_view(), name='telegram-auth'),
    path('api/auth/link/', LinkAccountView.as_view(), name='link-account'),
    path('api/auth/register/', RegisterView.as_view(), name='register'),
    path('api/auth/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('api/', include('api.urls')),
    path('', TemplateView.as_view(template_name='index.html'), name='miniapp'),
]

if settings.DEBUG:
    from django.conf.urls.static import static
    from api.dev_views import DevLoginPageView, DevUsersView, DevLoginView
    urlpatterns += [
        path('dev/', DevLoginPageView.as_view(), name='dev-login'),
        path('dev/users/', DevUsersView.as_view(), name='dev-users'),
        path('dev/login/', DevLoginView.as_view(), name='dev-login-api'),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
