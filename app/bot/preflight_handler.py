from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.bcgame_rounds import bcgame_round_service
from app.services.admin_ops import AdminOpsService
from app.services.market_data import market_data_service
from app.services.signal_intelligence import signal_intelligence_service

settings = get_settings()


def _owner_private_chat(update: Update) -> bool:
    return bool(
        settings.owner_telegram_id
        and update.effective_user
        and update.effective_user.id == settings.owner_telegram_id
        and update.effective_chat
        and update.effective_chat.type == 'private'
        and update.effective_chat.id == settings.owner_telegram_id
    )


async def preflight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Owner-only, read-only readiness check for a real recording session."""
    if not _owner_private_chat(update):
        if update.effective_chat:
            await update.effective_chat.send_message(
                'This command is available only in the owner private chat.'
            )
        return

    with SessionLocal() as db:
        signals_enabled = AdminOpsService(db).get_bool(
            AdminOpsService.SIGNALS_ENABLED_KEY,
            default=settings.signals_enabled,
        )

    snapshot = await market_data_service.cache.get_snapshot(
        settings.analysis_pair,
        settings.market_data_max_age_seconds,
    )
    candles = await market_data_service.get_cached_candles(settings.analysis_pair)
    candle_refresh_age = await market_data_service.cache.get_candle_refresh_age_seconds(
        settings.analysis_pair
    )
    trade_count, trade_span = await market_data_service.cache.get_trade_window_metrics(
        settings.analysis_pair,
        settings.signal_trade_flow_lookback_seconds,
    )

    timing_mode = settings.signal_timing_mode.upper()
    timing = None
    if timing_mode != 'MANUAL_SYNC':
        timing = await bcgame_round_service.current_round_decision()

    market_ready = bool(snapshot and snapshot.fresh)
    candles_ready = bool(candles)
    base_ready = (
        settings.signal_mode.upper() == 'LIVE'
        and signals_enabled
        and market_ready
        and candles_ready
    )
    if timing_mode == 'MANUAL_SYNC':
        timer_ready = True
        timer_text = 'MANUAL — no authoritative BCGAME countdown'
    elif timing and timing.actionable:
        timer_ready = True
        remaining = timing.remaining_seconds
        timer_text = (
            f'SYNCED — {remaining:.2f}s remaining'
            if remaining is not None
            else 'SYNCED — actionable round'
        )
    elif timing and not timing.synchronized and timing_mode == 'HYBRID_SYNC':
        timer_ready = False
        timer_text = 'FALLBACK AVAILABLE — authoritative timer is unavailable'
    else:
        timer_ready = False
        timer_text = f'WAIT — {timing.reason if timing else "timer unavailable"}'

    recording_ready = base_ready and timer_ready
    market_age = f'{snapshot.age_seconds:.3f}s' if snapshot else 'n/a'
    candle_age = f'{candle_refresh_age:.1f}s' if candle_refresh_age is not None else 'n/a'
    engine = signal_intelligence_service.operational_status()
    compute_ms = engine['last_compute_duration_ms']
    compute_text = f'{compute_ms} ms' if compute_ms is not None else 'not scanned since startup'

    await update.effective_chat.send_message(
        '🎬 LIVE RECORDING PREFLIGHT\n\n'
        f'Verdict: {"READY TO SCAN" if recording_ready else "WAIT — NOT READY"}\n'
        f'Signals: {"ON" if signals_enabled else "OFF"} • Mode: {settings.signal_mode.upper()}\n'
        f'BTC stream: {"FRESH" if market_ready else "NOT FRESH"} • age {market_age}\n'
        f'1m candles: {"READY" if candles_ready else "NOT READY"} • refresh age {candle_age}\n'
        f'Recent trades: {trade_count} across {trade_span:.1f}s (optional evidence)\n'
        f'BCGAME timer: {timer_text}\n'
        f'Last prediction compute: {compute_text}\n\n'
        'This confirms the technical scan path only. A safe scan may still return '
        'NO TRADE; no system can guarantee a winning 5-second outcome.'
    )
