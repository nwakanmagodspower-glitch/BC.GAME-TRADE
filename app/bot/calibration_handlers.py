from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from telegram import Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import Signal, SignalDirection, User

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


async def calibration_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return

    try:
        _, outcome_raw, signal_id_raw = query.data.split(':', 2)
        signal_id = int(signal_id_raw)
        outcome = outcome_raw.upper()
    except (ValueError, AttributeError):
        await query.answer('Invalid result label.', show_alert=True)
        return

    if outcome not in {'WIN', 'LOSS'}:
        await query.answer('Invalid result label.', show_alert=True)
        return

    with SessionLocal() as db:
        signal = db.get(Signal, signal_id)
        if signal is None:
            await query.answer('This signal is no longer available.', show_alert=True)
            return

        owner = bool(settings.owner_telegram_id and query.from_user.id == settings.owner_telegram_id)
        requester = db.get(User, signal.requested_by_user_id) if signal.requested_by_user_id else None
        owns_signal = bool(requester and requester.telegram_user_id == query.from_user.id)
        if not owner and not owns_signal:
            await query.answer('You cannot label this signal.', show_alert=True)
            return

        if signal.direction not in {SignalDirection.UP, SignalDirection.DOWN}:
            await query.answer('Only UP or DOWN signals can be labelled.', show_alert=True)
            return

        data = dict(signal.features_snapshot or {})
        existing = dict(data.get('_calibration') or {})
        existing.update({
            'bcgame_result': outcome,
            'source': 'USER_CONFIRMED_BCGAME',
            'labeled_by_telegram_id': query.from_user.id,
            'labeled_at': datetime.now(timezone.utc).isoformat(),
        })
        data['_calibration'] = existing
        signal.features_snapshot = data
        db.commit()

    await query.answer(f'BCGAME result saved: {outcome} ✅', show_alert=True)
    if query.message:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass


async def export_calibration_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _owner_private_chat(update):
        if update.effective_chat:
            await update.effective_chat.send_message('This command is available only in the owner private chat.')
        return

    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.temporary_retention_days)
    with SessionLocal() as db:
        signals = list(
            db.scalars(
                select(Signal)
                .where(Signal.created_at >= cutoff)
                .order_by(Signal.created_at.asc(), Signal.id.asc())
            )
        )

    if not signals:
        await update.effective_chat.send_message('No retained signal calibration records are available yet.')
        return

    buffer = io.StringIO()
    fieldnames = [
        'signal_id', 'created_at', 'strategy_version', 'market', 'product', 'direction',
        'external_reference_status', 'bcgame_result', 'bcgame_label_source',
        'scan_trigger_mode', 'scan_received_at', 'legacy_countdown_seconds',
        'quality', 'bull_score', 'bear_score', 'scan_price',
        'reference_entry_price', 'reference_expiry_price', 'trade_buy_ratio',
        'trade_count_recent', 'tick_return_1s_pct', 'tick_return_3s_pct',
        'tick_return_5s_pct', 'tick_acceleration_pct', 'tick_volatility_5s_pct',
        'ema_fast', 'ema_slow', 'rsi_14', 'atr_14_pct', 'volume_ratio',
        'taker_buy_ratio', 'structure', 'decision_reason', 'status_reason', 'features_json',
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()

    verified = 0
    for signal in signals:
        features = dict(signal.features_snapshot or {})
        decision = dict(features.get('_decision') or {})
        market = dict(features.get('_market') or {})
        round_meta = dict(features.get('_bcgame_round') or {})
        trigger = dict(features.get('_scan_trigger') or {})
        calibration = dict(features.get('_calibration') or {})
        if calibration.get('bcgame_result') in {'WIN', 'LOSS'}:
            verified += 1
        writer.writerow({
            'signal_id': signal.id,
            'created_at': signal.created_at.isoformat() if signal.created_at else '',
            'strategy_version': signal.strategy_version,
            'market': signal.market,
            'product': signal.product,
            'direction': signal.direction.value,
            'external_reference_status': signal.status.value,
            'bcgame_result': calibration.get('bcgame_result', ''),
            'bcgame_label_source': calibration.get('source', ''),
            'scan_trigger_mode': trigger.get('mode', ''),
            'scan_received_at': trigger.get('received_at', ''),
            'legacy_countdown_seconds': round_meta.get('countdown_confirmed_seconds', ''),
            'quality': decision.get('quality', ''),
            'bull_score': decision.get('bull_score', ''),
            'bear_score': decision.get('bear_score', ''),
            'scan_price': market.get('scan_price', ''),
            'reference_entry_price': signal.reference_entry_price or '',
            'reference_expiry_price': signal.reference_expiry_price or '',
            'trade_buy_ratio': features.get('trade_buy_ratio', ''),
            'trade_count_recent': features.get('trade_count_recent', ''),
            'tick_return_1s_pct': features.get('tick_return_1s_pct', ''),
            'tick_return_3s_pct': features.get('tick_return_3s_pct', ''),
            'tick_return_5s_pct': features.get('tick_return_5s_pct', ''),
            'tick_acceleration_pct': features.get('tick_acceleration_pct', ''),
            'tick_volatility_5s_pct': features.get('tick_volatility_5s_pct', ''),
            'ema_fast': features.get('ema_fast', ''),
            'ema_slow': features.get('ema_slow', ''),
            'rsi_14': features.get('rsi_14', ''),
            'atr_14_pct': features.get('atr_14_pct', ''),
            'volume_ratio': features.get('volume_ratio', ''),
            'taker_buy_ratio': features.get('taker_buy_ratio', ''),
            'structure': features.get('structure', ''),
            'decision_reason': signal.decision_reason or '',
            'status_reason': signal.status_reason or '',
            'features_json': json.dumps(features, separators=(',', ':'), sort_keys=True),
        })

    payload = buffer.getvalue().encode('utf-8')
    filename = f'bcgame-calibration-{datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")}.csv'
    document = io.BytesIO(payload)
    document.name = filename

    await update.effective_chat.send_message(
        f'🧠 CALIBRATION EXPORT\n\nRetained signals: {len(signals)}\nBCGAME-confirmed results: {verified}\nRetention window: {settings.temporary_retention_days} days\n\nNew scans include exact server-side Scan Now timestamps. Legacy countdown data is kept only for older records.'
    )
    await context.bot.send_document(chat_id=update.effective_chat.id, document=document, filename=filename)
