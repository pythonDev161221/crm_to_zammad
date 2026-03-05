import hashlib
import hmac
import json
from urllib.parse import unquote, parse_qsl

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User


def verify_telegram_init_data(init_data: str) -> dict | None:
    """
    Verify Telegram Mini App initData and return parsed user dict if valid.
    Returns None if verification fails.
    """
    parsed = dict(parse_qsl(unquote(init_data), keep_blank_values=True))
    received_hash = parsed.pop('hash', None)
    if not received_hash:
        return None

    data_check_string = '\n'.join(
        f'{k}={v}' for k, v in sorted(parsed.items())
    )

    secret_key = hmac.new(
        b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256
    ).digest()

    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    user_data = parsed.get('user')
    if not user_data:
        return None

    return json.loads(user_data)


class TelegramAuthView(APIView):
    permission_classes = []  # public endpoint

    def post(self, request):
        init_data = request.data.get('initData', '')
        user_data = verify_telegram_init_data(init_data)

        if not user_data:
            return Response({'detail': 'Invalid Telegram data.'}, status=status.HTTP_401_UNAUTHORIZED)

        telegram_id = user_data['id']
        user, _ = User.objects.get_or_create(
            telegram_id=telegram_id,
            defaults={
                'username': f'tg_{telegram_id}',
                'first_name': user_data.get('first_name', ''),
                'last_name': user_data.get('last_name', ''),
                'role': User.Role.WORKER,
            }
        )

        refresh = RefreshToken.for_user(user)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'role': user.role,
                'name': user.get_full_name() or user.username,
            }
        })
