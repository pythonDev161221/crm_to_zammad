"""
Development-only views. These are only registered when DEBUG=True.
Never exposed in production.
"""
import json

from django.http import JsonResponse, HttpResponseForbidden
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User


class DevLoginPageView(TemplateView):
    template_name = 'dev-login.html'

    def dispatch(self, request, *args, **kwargs):
        if not settings.DEBUG:
            return HttpResponseForbidden('Not available in production.')
        return super().dispatch(request, *args, **kwargs)


class DevUsersView(View):
    def get(self, request):
        users = User.objects.all().order_by('role', 'username')
        data = [
            {
                'id': u.id,
                'username': u.username,
                'name': u.get_full_name() or u.username,
                'role': u.role,
            }
            for u in users
        ]
        return JsonResponse(data, safe=False)


@method_decorator(csrf_exempt, name='dispatch')
class DevLoginView(View):
    def post(self, request):
        body = json.loads(request.body)
        user_id = body.get('user_id')

        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({'detail': 'User not found.'}, status=404)

        refresh = RefreshToken.for_user(user)
        return JsonResponse({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'role': user.role,
                'name': user.get_full_name() or user.username,
            }
        })
