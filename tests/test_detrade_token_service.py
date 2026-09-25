"""Tests for DeTradeTokenService — JWT extraction, validation, and DB persistence.

All database tests use an in-memory SQLite engine via the same pattern as the
rest of the test suite.
"""
from __future__ import annotations

import base64
import json
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.entities import AuditLog, RuntimeSetting
from app.services.detrade_token_service import (
    DETRADE_TOKEN_KEY,
    DeTradeTokenService,
    _extract_jwt,
)
from app.integrations.detrade_token_provider import detrade_token_is_expired


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jwt(exp_offset: int = 3600) -> str:
    """Build a syntactically valid JWT with a real exp claim."""
    header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
    payload = base64.urlsafe_b64encode(json.dumps({'sub': '1', 'exp': int(time.time()) + exp_offset}).encode()).rstrip(b'=').decode()
    sig = base64.urlsafe_b64encode(b'fakesig').rstrip(b'=').decode()
    return f'{header}.{payload}.{sig}'


def _expired_jwt() -> str:
    return _make_jwt(exp_offset=-3600)  # expired 1h ago


@pytest.fixture
def db_session():
    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        yield session


# ---------------------------------------------------------------------------
# _extract_jwt — raw text extraction
# ---------------------------------------------------------------------------

class TestExtractJwt:
    def test_extracts_bare_jwt(self):
        tok = _make_jwt()
        assert _extract_jwt(tok) == tok

    def test_extracts_from_websocket_url(self):
        tok = _make_jwt()
        url = f'wss://websocket.detrade.com/ws?token={tok}&extra=1'
        assert _extract_jwt(url) == tok

    def test_extracts_from_curl_command(self):
        tok = _make_jwt()
        curl = f"curl -H 'Authorization: Bearer {tok}' https://api.detrade.com/"
        assert _extract_jwt(curl) == tok

    def test_extracts_from_multiline_devtools_paste(self):
        tok = _make_jwt()
        block = f'GET /ws?token={tok} HTTP/1.1\nHost: websocket.detrade.com\nUpgrade: websocket'
        assert _extract_jwt(block) == tok

    def test_returns_none_when_no_jwt_present(self):
        assert _extract_jwt('hello world no token here') is None

    def test_returns_none_for_empty_string(self):
        assert _extract_jwt('') is None


# ---------------------------------------------------------------------------
# detrade_token_is_expired
# ---------------------------------------------------------------------------

class TestDeTradeTokenIsExpired:
    def test_valid_token_is_not_expired(self):
        tok = _make_jwt(exp_offset=3600)
        assert detrade_token_is_expired(tok) is False

    def test_expired_token_is_detected(self):
        tok = _expired_jwt()
        assert detrade_token_is_expired(tok) is True

    def test_none_is_not_expired(self):
        # No token means "not expired" (fails closed differently — usable check handles None)
        assert detrade_token_is_expired(None) is False

    def test_malformed_not_a_jwt_is_not_expired(self):
        # Malformed tokens should fail safe (not crash, not falsely mark as expired)
        assert detrade_token_is_expired('not.a.jwt') is False

    def test_custom_now_seconds(self):
        tok = _make_jwt(exp_offset=100)
        # Far in the future relative to the token — should be expired
        future = time.time() + 200
        assert detrade_token_is_expired(tok, now_seconds=future) is True


# ---------------------------------------------------------------------------
# DeTradeTokenService.update — full integration (in-memory DB)
# ---------------------------------------------------------------------------

class TestDeTradeTokenServiceUpdate:
    def test_accepts_valid_jwt(self, db_session):
        tok = _make_jwt()
        result = DeTradeTokenService(db_session).update(tok, actor_telegram_id=999)
        assert result.ok is True
        assert result.error is None
        assert result.expires_at is not None
        assert result.remaining_hours is not None
        assert result.remaining_hours > 0

    def test_rejects_string_with_no_jwt(self, db_session):
        result = DeTradeTokenService(db_session).update('no token here', actor_telegram_id=999)
        assert result.ok is False
        assert 'eyJ' in result.error or 'JWT' in result.error.upper() or 'token' in result.error.lower()

    def test_rejects_expired_jwt(self, db_session):
        tok = _expired_jwt()
        result = DeTradeTokenService(db_session).update(tok, actor_telegram_id=999)
        assert result.ok is False
        assert 'expired' in result.error.lower()

    def test_rejects_placeholder_token_literal(self, db_session):
        result = DeTradeTokenService(db_session).update('temporary', actor_telegram_id=999)
        assert result.ok is False

    def test_persists_token_to_db(self, db_session):
        tok = _make_jwt()
        DeTradeTokenService(db_session).update(tok, actor_telegram_id=999)
        row = db_session.get(RuntimeSetting, DETRADE_TOKEN_KEY)
        assert row is not None
        assert row.value == tok
        assert row.updated_by == 999

    def test_overwrites_existing_token(self, db_session):
        old = _make_jwt(exp_offset=100)
        new = _make_jwt(exp_offset=7200)
        DeTradeTokenService(db_session).update(old, actor_telegram_id=1)
        DeTradeTokenService(db_session).update(new, actor_telegram_id=1)
        row = db_session.get(RuntimeSetting, DETRADE_TOKEN_KEY)
        assert row.value == new

    def test_creates_audit_log_on_success(self, db_session):
        tok = _make_jwt()
        DeTradeTokenService(db_session).update(tok, actor_telegram_id=777)
        logs = db_session.query(AuditLog).filter_by(action='DETRADE_TOKEN_UPDATED').all()
        assert len(logs) == 1
        assert logs[0].actor_telegram_id == 777
        assert logs[0].target == 'detrade:token'

    def test_creates_audit_log_on_rejection(self, db_session):
        DeTradeTokenService(db_session).update('bad input', actor_telegram_id=777)
        logs = db_session.query(AuditLog).filter_by(action='DETRADE_TOKEN_REJECTED').all()
        assert len(logs) == 1

    def test_accepts_token_embedded_in_websocket_url(self, db_session):
        tok = _make_jwt()
        url = f'wss://websocket.detrade.com/ws?token={tok}'
        result = DeTradeTokenService(db_session).update(url, actor_telegram_id=999)
        assert result.ok is True
        row = db_session.get(RuntimeSetting, DETRADE_TOKEN_KEY)
        assert row.value == tok

    def test_accepts_token_embedded_in_curl_command(self, db_session):
        tok = _make_jwt()
        curl = f"curl 'https://api.detrade.com/' -H 'Authorization: Bearer {tok}'"
        result = DeTradeTokenService(db_session).update(curl, actor_telegram_id=999)
        assert result.ok is True


# ---------------------------------------------------------------------------
# DeTradeTokenService.get_persisted_token
# ---------------------------------------------------------------------------

class TestGetPersistedToken:
    def test_returns_none_when_no_token_stored(self, db_session):
        assert DeTradeTokenService(db_session).get_persisted_token() is None

    def test_returns_valid_token_when_stored(self, db_session):
        tok = _make_jwt()
        DeTradeTokenService(db_session).update(tok, actor_telegram_id=1)
        retrieved = DeTradeTokenService(db_session).get_persisted_token()
        assert retrieved == tok

    def test_returns_none_for_expired_stored_token(self, db_session):
        tok = _expired_jwt()
        # Bypass update() validation to force an expired token into DB
        db_session.add(RuntimeSetting(key=DETRADE_TOKEN_KEY, value=tok, updated_by=1))
        db_session.commit()
        retrieved = DeTradeTokenService(db_session).get_persisted_token()
        assert retrieved is None
