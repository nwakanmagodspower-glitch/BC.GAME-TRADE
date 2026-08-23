from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.services.signal_calibration import SignalCalibrationService

settings = get_settings()


def _is_owner(update: Update) -> bool:
    return bool(
        update.effective_user
        and update.effective_chat
        and update.effective_chat.type == 'private'
        and settings.owner_telegram_id
        and update.effective_user.id == settings.owner_telegram_id
        and update.effective_chat.id == settings.owner_telegram_id
    )


def _fmt(value, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f'{float(value):.{digits}f}'
    return 'n/a'


def _keyboard(signal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('✅ WIN', callback_data=f'calibration:win:{signal_id}'),
            InlineKeyboardButton('❌ LOSS', callback_data=f'calibration:loss:{signal_id}'),
        ],
        [InlineKeyboardButton('⏭ Skip', callback_data=f'calibration:skip:{signal_id}')],
        [InlineKeyboardButton('📊 Stats', callback_data='calibration:stats:0')],
    ])


def _signal_text(summary: dict) -> str:
    created = summary.get('created_at')
    created_text = created.isoformat(timespec='seconds') if created is not None else 'n/a'
    ratio = summary.get('trade_buy_ratio')
    ratio_text = f'{float(ratio) * 100:.1f}% buy' if isinstance(ratio, (int, float)) else 'n/a'
    return (
        '🧪 V2 PRIVATE CALIBRATION\n\n'
        f'Signal #{summary["id"]} • {summary["direction"]}\n'
        f'Time: {created_text}\n'
        f'Quality: {summary.get("quality") or "n/a"}\n'
        f'Unified edge: {_fmt(summary.get("edge"), 3)}\n'
        f'Time to BCGAME Start: {_fmt(summary.get("seconds_until_start"), 2)}s\n'
        f'Contract duration: {_fmt(summary.get("contract_duration_seconds"), 3)}s\n\n'
        f'BTC 1s / 3s / 5s: {_fmt(summary.get("return_1s"), 4)}% / '
        f'{_fmt(summary.get("return_3s"), 4)}% / {_fmt(summary.get("return_5s"), 4)}%\n'
        f'5s volatility: {_fmt(summary.get("volatility_5s"), 4)}%\n'
        f'Binance trade flow: {ratio_text}\n'
        f'Cross-venue state: {summary.get("cross_consensus") or "n/a"}\n\n'
        'Check this exact signal against the real BCGAME outcome, then label it.'
    )


async def calibrate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update) or not update.message:
        return
    with SessionLocal() as db:
        service = SignalCalibrationService(db)
        signal = service.latest_unlabeled()
        if signal is None:
            stats = service.stats()
            rate = 'n/a' if stats.win_rate is None else f'{stats.win_rate * 100:.1f}%'
            await update.message.reply_text(
                '🧪 V2 PRIVATE CALIBRATION\n\nNo unlabeled V2 directional signal is available yet.\n'
                f'Labeled: {stats.labeled} • W {stats.wins} / L {stats.losses} • Win rate {rate}'
            )
            return
        summary = service.signal_summary(signal)
    await update.message.reply_text(_signal_text(summary), reply_markup=_keyboard(signal.id))


async def calibration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not _is_owner(update):
        if query:
            await query.answer('Owner-only calibration.', show_alert=True)
        return

    parts = (query.data or '').split(':')
    if len(parts) != 3:
        await query.answer('Invalid calibration action.', show_alert=True)
        return
    _, action, raw_id = parts

    if action == 'stats':
        await query.answer()
        with SessionLocal() as db:
            stats = SignalCalibrationService(db).stats()
        rate = 'n/a' if stats.win_rate is None else f'{stats.win_rate * 100:.1f}%'
        win_edge = 'n/a' if stats.avg_win_edge is None else f'{stats.avg_win_edge:.3f}'
        loss_edge = 'n/a' if stats.avg_loss_edge is None else f'{stats.avg_loss_edge:.3f}'
        await query.message.reply_text(
            '📊 V2 CALIBRATION STATS\n\n'
            f'Labeled: {stats.labeled}\nWins: {stats.wins}\nLosses: {stats.losses}\n'
            f'Win rate: {rate}\nAverage winning edge: {win_edge}\nAverage losing edge: {loss_edge}'
        )
        return

    try:
        signal_id = int(raw_id)
    except ValueError:
        await query.answer('Invalid signal ID.', show_alert=True)
        return

    if action in {'win', 'loss'}:
        with SessionLocal() as db:
            service = SignalCalibrationService(db)
            try:
                service.label(signal_id, action.upper(), query.from_user.id)
            except ValueError as exc:
                await query.answer(str(exc), show_alert=True)
                return
        await query.answer(f'{action.upper()} saved')
        await query.edit_message_reply_markup(None)
    elif action == 'skip':
        await query.answer('Skipped')
        await query.edit_message_reply_markup(None)
    else:
        await query.answer('Unknown calibration action.', show_alert=True)
        return

    with SessionLocal() as db:
        service = SignalCalibrationService(db)
        next_signal = service.latest_unlabeled()
        stats = service.stats()
        next_summary = service.signal_summary(next_signal) if next_signal is not None else None

    if next_signal is not None and next_summary is not None:
        await query.message.reply_text(_signal_text(next_summary), reply_markup=_keyboard(next_signal.id))
    else:
        rate = 'n/a' if stats.win_rate is None else f'{stats.win_rate * 100:.1f}%'
        await query.message.reply_text(
            f'Calibration queue complete for now. Labeled {stats.labeled}: '
            f'W {stats.wins} / L {stats.losses} • {rate}.'
        )
