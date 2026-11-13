from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.models.entities import User

logger = logging.getLogger(__name__)


def _sha256(val: str | int | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip().lower()
    if not s:
        return None
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def _format_fbc(fbclid: str | None, timestamp: int) -> str | None:
    if not fbclid:
        return None
    cleaned = fbclid.strip()
    if not cleaned:
        return None
    if cleaned.startswith('fb.1.'):
        return cleaned
    return f'fb.1.{timestamp}.{cleaned}'


class MetaCAPIService:
    """Dispatches server-side attribution events to Meta Conversions API (CAPI).

    Tracks the full affiliate trader acquisition funnel:
      - Lead: User starts Telegram bot / joins VIP channel
      - CompleteRegistration: User submits verified BCGAME numeric UID
      - Purchase: Admin approves user deposit / subscription value in NGN
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._client = http_client

    async def send_event(
        self,
        event_name: str,
        user: User,
        custom_data: dict[str, Any] | None = None,
        event_id: str | None = None,
        event_source_url: str | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        pixel_id = settings.meta_pixel_id
        access_token = settings.meta_capi_access_token

        if not pixel_id or not access_token:
            logger.debug(
                'Meta CAPI skipped for event "%s": pixel_id or access_token not configured.',
                event_name,
            )
            return {'status': 'skipped', 'reason': 'not_configured'}

        now_sec = int(time.time())
        url = f'https://graph.facebook.com/v19.0/{pixel_id}/events'

        # Build user_data conforming to Meta Conversions API specifications
        user_data: dict[str, Any] = {}
        if user.telegram_user_id:
            hashed_id = _sha256(user.telegram_user_id)
            if hashed_id:
                user_data['external_id'] = [hashed_id]

        if user.first_name:
            hashed_fn = _sha256(user.first_name)
            if hashed_fn:
                user_data['fn'] = [hashed_fn]

        # Attribution: fbc click parameter
        fbc = _format_fbc(user.fbclid, now_sec)
        if fbc:
            user_data['fbc'] = fbc

        source_url = event_source_url or settings.bridge_url or 'https://t.me/bcgame_trade_bot'

        event_payload: dict[str, Any] = {
            'event_name': event_name,
            'event_time': now_sec,
            'action_source': 'website',
            'event_source_url': source_url,
            'user_data': user_data,
        }

        if event_id:
            event_payload['event_id'] = event_id
        else:
            # Deterministic/semi-unique event ID for deduplication
            event_payload['event_id'] = f'{event_name.lower()}_{user.telegram_user_id}_{now_sec}'

        if custom_data:
            event_payload['custom_data'] = custom_data

        root_payload: dict[str, Any] = {
            'data': [event_payload],
        }

        if settings.meta_test_event_code:
            root_payload['test_event_code'] = settings.meta_test_event_code

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
        }

        try:
            if self._client is not None:
                resp = await self._client.post(url, json=root_payload, headers=headers, timeout=5.0)
            else:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(url, json=root_payload, headers=headers)

            if resp.status_code == 200:
                logger.info('Meta CAPI event "%s" successfully sent for user %s', event_name, user.telegram_user_id)
                return {'status': 'success', 'response': resp.json()}
            else:
                logger.warning(
                    'Meta CAPI event "%s" returned HTTP %d: %s',
                    event_name,
                    resp.status_code,
                    resp.text,
                )
                return {'status': 'failed', 'http_code': resp.status_code, 'body': resp.text}
        except Exception as exc:
            logger.warning('Meta CAPI event "%s" failed with exception: %s', event_name, exc)
            return {'status': 'error', 'error': str(exc)}

    async def send_lead_event(self, user: User, event_source_url: str | None = None) -> dict[str, Any]:
        """Triggered when a trader enters the Telegram onboarding funnel."""
        return await self.send_event(
            event_name='Lead',
            user=user,
            custom_data={'content_name': 'VIP AI Signal Registration Pass'},
            event_id=f'lead_{user.telegram_user_id}',
            event_source_url=event_source_url,
        )

    async def send_registration_event(
        self,
        user: User,
        bcgame_id: str | None = None,
        event_source_url: str | None = None,
    ) -> dict[str, Any]:
        """Triggered when user submits valid BCGAME numeric UID."""
        custom_data: dict[str, Any] = {
            'content_name': 'BCGAME Account Registered',
            'status': 'registered',
        }
        if bcgame_id:
            custom_data['content_category'] = 'bcgame_uid'
        return await self.send_event(
            event_name='CompleteRegistration',
            user=user,
            custom_data=custom_data,
            event_id=f'reg_{user.telegram_user_id}',
            event_source_url=event_source_url,
        )

    async def send_purchase_event(
        self,
        user: User,
        amount_ngn: float = 25000.0,
        tier_name: str | None = None,
        event_source_url: str | None = None,
    ) -> dict[str, Any]:
        """Triggered when admin approves the deposit verification request."""
        custom_data = {
            'currency': 'NGN',
            'value': float(amount_ngn),
            'content_name': tier_name or 'VIP Signal Access Deposit Verified',
            'content_type': 'product',
        }
        return await self.send_event(
            event_name='Purchase',
            user=user,
            custom_data=custom_data,
            event_id=f'purchase_{user.telegram_user_id}_{int(time.time())}',
            event_source_url=event_source_url,
        )


meta_capi_service = MetaCAPIService()

