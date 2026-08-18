from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.integrations.bcgame_rounds import bcgame_round_service
from app.models.entities import Broadcast, Signal, SignalStatus, User, UserStatus
from app.services.admin_ops import AdminOpsService
from app.services.broadcasts import BroadcastService
from app.services.market_data import market_data_service
from app.services.paper_validation import PaperValidationService
from app.services.worker_status import get_worker_status

settings = get_settings()


def _is_owner(update: Update) -> bool:
    return bool(update.effective_user and settings.owner_telegram_id and update.effective_user.id == settings.owner_telegram_id)


def _admin_menu(signals_enabled: bool) -> InlineKeyboardMarkup:
    signal_label = '🛑 Disable Signals' if signals_enabled else '▶️ Enable Signals'
    signal_action = 'adminops:signals:off' if signals_enabled else 'adminops:signals:on'
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 System Status', callback_data='adminops:status')],
        [InlineKeyboardButton('🧪 Paper Validation', callback_data='adminops:paper_validation')],
        [InlineKeyboardButton(signal_label, callback_data=signal_action)],
        [InlineKeyboardButton('📣 Broadcast Help', callback_data='adminops:broadcast_help')],
        [InlineKeyboardButton('👤 User Controls Help', callback_data='adminops:user_help')],
    ])


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update):
        return
    with SessionLocal() as db:
        enabled = AdminOpsService(db).get_bool(AdminOpsService.SIGNALS_ENABLED_KEY, settings.signals_enabled)
    await update.effective_chat.send_message('🔐 BC.GAME TRADE — OWNER PANEL', reply_markup=_admin_menu(enabled))


async def admin_ops_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not _is_owner(update):
        if query:
            await query.answer('Owner access required.', show_alert=True)
        return
    await query.answer(); data = query.data or ''

    if data == 'adminops:status':
        with SessionLocal() as db:
            ops = AdminOpsService(db)
            enabled = ops.get_bool(ops.SIGNALS_ENABLED_KEY, settings.signals_enabled)
            approved = int(db.scalar(select(func.count(User.id)).where(User.status == UserStatus.APPROVED, User.is_blocked.is_(False))) or 0)
            waiting = int(db.scalar(select(func.count(Signal.id)).where(Signal.status == SignalStatus.WAITING_ENTRY)) or 0)
            active = int(db.scalar(select(func.count(Signal.id)).where(Signal.status == SignalStatus.ACTIVE)) or 0)
            latest_broadcast = db.scalar(select(Broadcast).order_by(Broadcast.id.desc()))
            worker = get_worker_status(db)
        snap = await market_data_service.cache.get_snapshot(settings.analysis_pair, settings.market_data_max_age_seconds)
        rounds = bcgame_round_service.status()
        bcast = 'none' if latest_broadcast is None else f'#{latest_broadcast.id} {latest_broadcast.status.value} ({latest_broadcast.sent_count}/{latest_broadcast.recipient_count})'
        text = (
            '📊 SYSTEM STATUS\n\n'
            f'Product: {settings.game_market} • 5s • ${settings.default_stake_band}\n'
            f'Strategy: {settings.strategy_version}\n'
            f'Mode: {settings.signal_mode}\n'
            f'Signals: {"ON" if enabled else "OFF"}\n'
            f'External BTC feed: {"FRESH" if snap and snap.fresh else "NOT FRESH"}\n'
            f'Worker: {"FRESH" if worker.fresh else "NOT FRESH"}\n'
            f'BC.GAME round sync: {"FRESH" if rounds.fresh else ("ENABLED / NOT FRESH" if rounds.enabled else "OFF") }\n'
            f'Action window: {settings.signal_minimum_action_lead_seconds}-{settings.signal_maximum_action_lead_seconds}s before lock\n'
            f'Approved users: {approved}\nWaiting signals: {waiting}\nActive signals: {active}\n'
            f'Latest broadcast: {bcast}'
        )
        await query.message.reply_text(text); return

    if data == 'adminops:paper_validation':
        with SessionLocal() as db:
            report = PaperValidationService(db).build_report()
        entry_avg = 'n/a' if report.avg_entry_delay_seconds is None else f'{report.avg_entry_delay_seconds:.3f}s'
        entry_max = 'n/a' if report.max_entry_delay_seconds is None else f'{report.max_entry_delay_seconds:.3f}s'
        settle_avg = 'n/a' if report.avg_settlement_delay_seconds is None else f'{report.avg_settlement_delay_seconds:.3f}s'
        blockers = 'None' if not report.blockers else '\n'.join(f'• {b}' for b in report.blockers)
        text = (
            '🧪 5s PAPER VALIDATION\n\n'
            f'Scans: {report.total_scans}\nDirectional: {report.directional_signals}\nNO TRADE: {report.no_trade}\n'
            f'Settled external refs: {report.settled} (W {report.wins} / L {report.losses} / T {report.ties})\n'
            f'Cancelled: {report.cancelled}\nStuck active: {report.stuck_active}\n'
            f'Start delay avg/max: {entry_avg} / {entry_max}\nEnd-reference delay avg: {settle_avg}\n'
            f'Missing start/end refs: {report.missing_entry_prices}/{report.missing_expiry_prices}\n'
            f'Technical gate: {"PASSABLE" if report.passable else "BLOCKED"}\n\nBlockers:\n{blockers}\n\n'
            'Note: external-reference W/L is diagnostic until BC.GAME Start/End Rate ingestion is verified.'
        )
        await query.message.reply_text(text); return

    if data in {'adminops:signals:on', 'adminops:signals:off'}:
        enabled = data.endswith(':on')
        if enabled and settings.signal_mode.upper() == 'LIVE' and not bcgame_round_service.status().fresh:
            await query.message.reply_text('Cannot enable LIVE signals: BC.GAME round synchronization is not fresh.')
            return
        with SessionLocal() as db:
            AdminOpsService(db).set_signals_enabled(enabled, query.from_user.id)
        await query.message.reply_text(f'Signals are now {"ON" if enabled else "OFF"}.', reply_markup=_admin_menu(enabled)); return

    if data == 'adminops:broadcast_help':
        await query.message.reply_text('Broadcast commands:\n/broadcast Your message — create preview\n\nNothing is sent until you confirm the preview button.'); return
    if data == 'adminops:user_help':
        await query.message.reply_text('User controls:\n/suspend <Telegram ID>\n/restore <Telegram ID>')


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_owner(update) or not update.message:
        return
    message = ' '.join(context.args or []).strip()
    if not message:
        await update.message.reply_text('Usage: /broadcast Your message'); return
    with SessionLocal() as db:
        service = BroadcastService(db)
        try:
            broadcast = service.create_draft(message, update.effective_user.id)
        except ValueError as exc:
            await update.message.reply_text(str(exc)); return
        recipients = service.approved_recipient_count()
    preview = f'📣 BROADCAST PREVIEW\n\n{message}\n\nApproved recipients now: {recipients}\n\nConfirming will freeze the eligible recipient list and queue delivery.'
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ Confirm Broadcast', callback_data=f'adminops:broadcast_confirm:{broadcast.id}')],
        [InlineKeyboardButton('❌ Cancel', callback_data=f'adminops:broadcast_cancel:{broadcast.id}')],
    ])
    await update.message.reply_text(preview, reply_markup=keyboard)


async def broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not _is_owner(update):
        return
    try:
        _, action, broadcast_id_text = (query.data or '').rsplit(':', 2); broadcast_id = int(broadcast_id_text)
    except ValueError:
        await query.answer('Invalid broadcast action.', show_alert=True); return
    with SessionLocal() as db:
        service = BroadcastService(db)
        try:
            if action == 'broadcast_confirm':
                broadcast = service.queue(broadcast_id, query.from_user.id); await query.answer('Queued'); await query.edit_message_reply_markup(None)
                await query.message.reply_text(f'Broadcast #{broadcast.id} queued for {broadcast.recipient_count} approved users.')
            elif action == 'broadcast_cancel':
                service.cancel_draft(broadcast_id, query.from_user.id); await query.answer('Cancelled'); await query.edit_message_reply_markup(None)
                await query.message.reply_text('Broadcast draft cancelled.')
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)


async def _change_user_status(update: Update, context: ContextTypes.DEFAULT_TYPE, restore: bool):
    if not _is_owner(update) or not update.message:
        return
    if not context.args:
        await update.message.reply_text(f'Usage: /{"restore" if restore else "suspend"} <Telegram ID>'); return
    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('Telegram ID must be a number.'); return
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_user_id == telegram_id))
        if not user:
            await update.message.reply_text('User not found.'); return
        try:
            changed = AdminOpsService(db).restore_user(user.id, update.effective_user.id) if restore else AdminOpsService(db).suspend_user(user.id, update.effective_user.id)
        except ValueError as exc:
            await update.message.reply_text(str(exc)); return
    await update.message.reply_text(f'User {changed.telegram_user_id} is now {changed.status.value}.')
    try:
        await context.bot.send_message(changed.telegram_user_id, 'Your BC.GAME TRADE access has been restored.' if restore else 'Your BC.GAME TRADE access has been suspended. Please contact support if needed.')
    except Exception:
        pass


async def suspend_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await _change_user_status(update, context, False)
async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE): await _change_user_status(update, context, True)
