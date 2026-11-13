from __future__ import annotations

import hashlib
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.models.entities import User, UserStatus
from app.services.meta_capi import MetaCAPIService, _format_fbc, _sha256


def test_sha256_and_fbc_helpers():
    assert _sha256(None) is None
    assert _sha256('') is None
    expected_hash = hashlib.sha256(b'12345678').hexdigest()
    assert _sha256(12345678) == expected_hash
    assert _sha256(' 12345678 ') == expected_hash

    now_ts = 1710000000
    assert _format_fbc(None, now_ts) is None
    assert _format_fbc('', now_ts) is None
    assert _format_fbc('click123', now_ts) == 'fb.1.1710000000.click123'
    assert _format_fbc('fb.1.9999.already_formatted', now_ts) == 'fb.1.9999.already_formatted'


@pytest.mark.asyncio
async def test_capi_skipped_when_unconfigured():
    service = MetaCAPIService()
    user = User(
        id=1,
        telegram_user_id=987654321,
        first_name='Emeka',
        status=UserStatus.PENDING,
        fbclid='sample_fbclid_123',
    )
    with patch('app.services.meta_capi.get_settings', return_value=Settings(meta_pixel_id=None, meta_capi_access_token=None)):
        res = await service.send_lead_event(user)
        assert res['status'] == 'skipped'
        assert res['reason'] == 'not_configured'

        res_reg = await service.send_registration_event(user, bcgame_id='777888')
        assert res_reg['status'] == 'skipped'

        res_purch = await service.send_purchase_event(user, amount_ngn=25000.0)
        assert res_purch['status'] == 'skipped'


@pytest.mark.asyncio
async def test_capi_send_lead_event_payload():
    mock_response = httpx.Response(
        status_code=200,
        json={'events_received': 1, 'messages': []},
        request=httpx.Request('POST', 'https://graph.facebook.com/v19.0/123456/events'),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    service = MetaCAPIService(http_client=mock_client)
    user = User(
        id=1,
        telegram_user_id=11223344,
        first_name='Tunde',
        status=UserStatus.PENDING,
        fbclid='IwAR_test_click',
    )

    test_settings = Settings(
        meta_pixel_id='123456789',
        meta_capi_access_token='EAA_test_token',
        meta_test_event_code='TEST999',
        bridge_url='https://bridge.example.com',
    )

    with patch('app.services.meta_capi.get_settings', return_value=test_settings):
        result = await service.send_lead_event(user)
        assert result['status'] == 'success'
        assert mock_client.post.called

        _, kwargs = mock_client.post.call_args
        headers = kwargs['headers']
        assert headers['Authorization'] == 'Bearer EAA_test_token'

        json_data = kwargs['json']
        assert json_data['test_event_code'] == 'TEST999'
        assert len(json_data['data']) == 1

        ev = json_data['data'][0]
        assert ev['event_name'] == 'Lead'
        assert ev['event_source_url'] == 'https://bridge.example.com'
        assert ev['action_source'] == 'website'
        assert ev['user_data']['external_id'] == [_sha256(11223344)]
        assert ev['user_data']['fn'] == [_sha256('tunde')]
        assert ev['user_data']['fbc'].startswith('fb.1.')
        assert 'IwAR_test_click' in ev['user_data']['fbc']


@pytest.mark.asyncio
async def test_capi_send_registration_and_purchase():
    mock_response = httpx.Response(
        status_code=200,
        json={'events_received': 1},
        request=httpx.Request('POST', 'https://graph.facebook.com/v19.0/123456/events'),
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.return_value = mock_response

    service = MetaCAPIService(http_client=mock_client)
    user = User(
        id=2,
        telegram_user_id=55667788,
        first_name='Chidi',
        status=UserStatus.PENDING,
        fbclid=None,
    )

    test_settings = Settings(
        meta_pixel_id='123456789',
        meta_capi_access_token='EAA_test_token',
    )

    with patch('app.services.meta_capi.get_settings', return_value=test_settings):
        # Registration event
        reg_result = await service.send_registration_event(user, bcgame_id='998877')
        assert reg_result['status'] == 'success'
        ev_reg = mock_client.post.call_args[1]['json']['data'][0]
        assert ev_reg['event_name'] == 'CompleteRegistration'
        assert ev_reg['custom_data']['status'] == 'registered'
        assert ev_reg['custom_data']['content_category'] == 'bcgame_uid'
        assert 'fbc' not in ev_reg['user_data']

        # Purchase event
        purch_result = await service.send_purchase_event(
            user,
            amount_ngn=50000.0,
            tier_name='VIP 30-Day',
        )
        assert purch_result['status'] == 'success'
        ev_purch = mock_client.post.call_args[1]['json']['data'][0]
        assert ev_purch['event_name'] == 'Purchase'
        assert ev_purch['custom_data']['value'] == 50000.0
        assert ev_purch['custom_data']['currency'] == 'NGN'
        assert ev_purch['custom_data']['content_name'] == 'VIP 30-Day'


@pytest.mark.asyncio
async def test_capi_resilience_on_network_or_http_error():
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post.side_effect = httpx.ConnectError('DNS Resolution Failure')

    service = MetaCAPIService(http_client=mock_client)
    user = User(id=3, telegram_user_id=123, first_name='Test', status=UserStatus.PENDING)

    test_settings = Settings(meta_pixel_id='123', meta_capi_access_token='tok')
    with patch('app.services.meta_capi.get_settings', return_value=test_settings):
        # Should gracefully return error dict, never raising to caller
        res = await service.send_lead_event(user)
        assert res['status'] == 'error'
        assert 'DNS Resolution Failure' in res['error']


def test_bridge_redirect_endpoints():
    client = TestClient(app)

    # 1. No fbclid -> redirects to ?start=welcome
    resp1 = client.get('/bridge', follow_redirects=False)
    assert resp1.status_code == 307
    location1 = resp1.headers['location']
    assert location1.startswith('https://t.me/')
    assert location1.endswith('?start=welcome')

    # 2. With fbclid -> redirects to ?start=fbclid_<id>
    resp2 = client.get('/bridge?fbclid=IwAR999_ClickID', follow_redirects=False)
    assert resp2.status_code == 307
    location2 = resp2.headers['location']
    assert location2.endswith('?start=fbclid_IwAR999_ClickID')

    # 3. Custom bot username in query
    resp3 = client.get('/lander?bot=my_test_bot&fbclid=abc123xyz', follow_redirects=False)
    assert resp3.status_code == 307
    assert resp3.headers['location'] == 'https://t.me/my_test_bot?start=fbclid_abc123xyz'


def test_tier_bands_clean_no_recommended():
    from app.bot.handlers import TIER_INFO
    assert 'starter' in TIER_INFO
    assert 'pro' in TIER_INFO
    assert 'vip' in TIER_INFO

    assert '₦5,000 – ₦15,000' in TIER_INFO['starter']['name']
    assert '₦15,000 – ₦35,000' in TIER_INFO['pro']['name']
    assert '₦35,000 – ₦100,000+' in TIER_INFO['vip']['name']

    for key, info in TIER_INFO.items():
        assert 'Recommended' not in info['name']
        assert 'Recommended' not in info['trial']
        assert 'Most Popular' not in info['name']
        assert 'Most Popular' not in info['trial']


