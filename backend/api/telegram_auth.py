import hashlib
import hmac
import json
from urllib.parse import unquote, parse_qsl

from django.conf import settings
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import User, StationInvite, RoleInvite


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
        try:
            user = User.objects.get(telegram_id=telegram_id)
        except User.DoesNotExist:
            return Response({'needs_linking': True}, status=status.HTTP_200_OK)

        if not user.is_active:
            return Response({'needs_linking': True, 'inactive': True}, status=status.HTTP_200_OK)

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


class LinkAccountView(APIView):
    permission_classes = []  # public endpoint

    def post(self, request):
        init_data = request.data.get('initData', '')
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '')

        user_data = verify_telegram_init_data(init_data)
        if not user_data:
            return Response({'detail': 'Invalid Telegram data.'}, status=status.HTTP_401_UNAUTHORIZED)

        telegram_id = user_data['id']

        if User.objects.filter(telegram_id=telegram_id).exists():
            return Response({'detail': 'This Telegram account is already linked.'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(username=username, password=password)
        if not user:
            return Response({'detail': 'Invalid username or password.'}, status=status.HTTP_401_UNAUTHORIZED)

        if user.telegram_id:
            return Response({'detail': 'This account is already linked to another Telegram user.'}, status=status.HTTP_400_BAD_REQUEST)

        user.telegram_id = telegram_id
        user.save(update_fields=['telegram_id'])

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


class RegisterView(APIView):
    permission_classes = []  # public endpoint

    def post(self, request):
        init_data = request.data.get('initData', '')
        token = request.data.get('token', '').strip()
        first_name = request.data.get('first_name', '').strip()
        last_name = request.data.get('last_name', '').strip()

        user_data = verify_telegram_init_data(init_data)
        if not user_data:
            return Response({'detail': 'Invalid Telegram data.'}, status=status.HTTP_401_UNAUTHORIZED)

        telegram_id = user_data['id']

        # Re-activate an inactive account via invite
        existing = User.objects.filter(telegram_id=telegram_id).first()
        if existing and existing.is_active:
            return Response({'detail': 'This Telegram account is already registered.'}, status=status.HTTP_400_BAD_REQUEST)

        # Try StationInvite first, then RoleInvite
        station_invite = StationInvite.objects.select_related('station').filter(token=token, is_active=True).first()
        role_invite = None
        if not station_invite:
            role_invite = RoleInvite.objects.select_related('company', 'station').filter(token=token, is_used=False).first()
        if not station_invite and not role_invite:
            return Response({'detail': 'Invalid or expired invite link.'}, status=status.HTTP_400_BAD_REQUEST)

        def _make_username(user_data):
            tg_username = user_data.get('username', '')
            base = tg_username or f'user_{user_data["id"]}'
            username = base
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f'{base}_{counter}'
                counter += 1
            return username

        if station_invite:
            if existing and not existing.is_active:
                existing.is_active = True
                existing.station = station_invite.station
                existing.role = User.Role.WORKER
                if first_name:
                    existing.first_name = first_name
                if last_name:
                    existing.last_name = last_name
                existing.save(update_fields=['is_active', 'station', 'role', 'first_name', 'last_name'])
                worker = existing
            else:
                worker = User.objects.create_user(
                    username=_make_username(user_data),
                    password=None,
                    first_name=first_name or user_data.get('first_name', ''),
                    last_name=last_name or user_data.get('last_name', ''),
                    role=User.Role.WORKER,
                    station=station_invite.station,
                    telegram_id=telegram_id,
                )
        else:
            # RoleInvite
            role = role_invite.role
            if existing and not existing.is_active:
                existing.is_active = True
                existing.role = role
                if first_name:
                    existing.first_name = first_name
                if last_name:
                    existing.last_name = last_name
                existing.save(update_fields=['is_active', 'role', 'first_name', 'last_name'])
                worker = existing
            else:
                worker = User.objects.create_user(
                    username=_make_username(user_data),
                    password=None,
                    first_name=first_name or user_data.get('first_name', ''),
                    last_name=last_name or user_data.get('last_name', ''),
                    role=role,
                    telegram_id=telegram_id,
                )
            worker.companies.add(role_invite.company)
            if role == RoleInvite.Role.STATION_MANAGER and role_invite.station:
                role_invite.station.manager = worker
                role_invite.station.save(update_fields=['manager'])
            role_invite.is_used = True
            role_invite.save(update_fields=['is_used'])

        refresh = RefreshToken.for_user(worker)
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': worker.id,
                'role': worker.role,
                'name': worker.get_full_name() or worker.username,
            }
        }, status=status.HTTP_201_CREATED)
