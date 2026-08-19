from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.signal_views import (
    build_scan_prompt_keyboard,
    build_signal_keyboard,
    format_scan_context,
    format_signal,
)
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import OnboardingStep, Signal, UserStatus
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService

settings = get_settings()


def _button(label: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]])


def _approved_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('⚡ BTC 5s Signal', callback_data='menu:signal')],
        [InlineKeyboardButton('📈 My Results', callback_data='menu:results')],
        [InlineKeyboardButton('ℹ️ How It Works', callback_data='menu:help')],
        [InlineKeyboardButton('🆘 Support', callback_data='menu:support')],
    ])


def _is_access_blocked(user) -> bool:
    return bool(user.is_blocked or user.status == UserStatus.SUSPENDED)


def _result_label(signal: Signal) -> str:
    source = str(((signal.features_snapshot or {}).get('_bcgame_round') or {}).get('source') or '')
    if source == 'MANUAL_SYNC' and signal.status.value in {'WIN', 'LOSS', 'TIE'}:
        return f'{signal.status.value} (external reference only)'
    if signal.status.value == 'EXPIRED':
        return 'UNRESOLVED'
    return signal.status.value


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    if not tg_user or not update.effective_chat:
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(tg_user)
        if user.is_blocked:
            await update.effective_chat.send_message('Your access is blocked. Please contact support.')
            return
        if user.status == UserStatus.APPROVED:
            await update.effective_chat.send_message(
                '⚡ BC.GAME BTC 5s Signals\n\nYour access is active. Choose an option.',
                reply_markup=_approved_menu(),
            )
            return
        if user.status == UserStatus.SUSPENDED:
            await update.effective_chat.send_message('Your access is suspended. Please contact support.')
            return
        if user.status == UserStatus.REJECTED:
            await update.effective_chat.send_message('Your verification was not approved. Please contact support if needed.')
            return

        step = user.onboarding_step
        if step == OnboardingStep.START:
            service.set_step(user, OnboardingStep.REGISTRATION)
            step = OnboardingStep.REGISTRATION

        if step == OnboardingStep.REGISTRATION:
            keyboard = []
            if settings.bcgame_registration_url:
                keyboard.append([InlineKeyboardButton('🔗 Register on BC.GAME', url=settings.bcgame_registration_url)])
            keyboard.append([InlineKeyboardButton('✅ I Have Registered', callback_data='onboard:registered')])
            await update.effective_chat.send_message(
                'Welcome to BC.GAME BTC 5s Signals.\n\n'
                'Access is verified manually so signals remain limited to approved users.\n\n'
                'Step 1 of 5 — Registration\n'
                'Create your BC.GAME account using the link below, then return here.',
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        if step == OnboardingStep.DEPOSIT:
            await _send_deposit_step(update)
            return
        if step == OnboardingStep.BC_ID:
            await update.effective_chat.send_message('Step 3 of 5 — BC.GAME User ID\n\nSend your BC.GAME User ID as text.')
            return
        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('Step 4 of 5 — Profile Proof\n\nSend a clear screenshot of your BC.GAME profile showing the User ID.')
            return
        if step == OnboardingStep.DEPOSIT_PROOF:
            await update.effective_chat.send_message(
                'Step 5 of 5 — Deposit Proof\n\nSend one or more clear deposit screenshots. When finished, tap Finish Verification.',
                reply_markup=_button('✅ Finish Verification', 'onboard:submit'),
            )
            return
        if step == OnboardingStep.REVIEW:
            await update.effective_chat.send_message('⏳ Verification submitted. Your request is waiting for manual review.')
            return
        if step == OnboardingStep.RESUBMIT:
            await update.effective_chat.send_message('🔄 Resubmission requested. Send your BC.GAME User ID to start a new evidence packet.')


async def _send_deposit_step(update: Update):
    keyboard = []
    if settings.bcgame_deposit_url:
        keyboard.append([InlineKeyboardButton('💳 Open Deposit Page', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('✅ I Have Deposited', callback_data='onboard:deposited')])
    await update.effective_chat.send_message(
        'Step 2 of 5 — Deposit\n\nMake your deposit on BC.GAME. When complete, return here and continue.',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(query.from_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            await query.answer('This onboarding action is not available.', show_alert=True)
            return
        if query.data == 'onboard:registered' and user.onboarding_step == OnboardingStep.REGISTRATION:
            service.set_step(user, OnboardingStep.DEPOSIT)
            await query.edit_message_text('Registration saved ✅')
            await _send_deposit_step(update)
            return
        if query.data == 'onboard:deposited' and user.onboarding_step == OnboardingStep.DEPOSIT:
            service.set_step(user, OnboardingStep.BC_ID)
            await query.edit_message_text('Deposit step saved ✅\n\nStep 3 of 5 — Send your BC.GAME User ID as text.')
            return
        if query.data == 'onboard:submit' and user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try:
                request = service.submit(user)
            except ValueError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            await query.edit_message_text('Verification submitted ✅\n\nYou will receive a message after manual review.')
            return
        await query.answer('That step is no longer active.', show_alert=True)


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user:
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(update.effective_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            return
        if user.onboarding_step == OnboardingStep.BC_ID:
            value = update.message.text.strip()
            if len(value) < 2 or len(value) > 255:
                await update.message.reply_text('Please send a valid BC.GAME User ID.')
                return
            service.set_bcgame_user_id(user, value)
            await update.message.reply_text('User ID saved ✅\n\nNow send a profile screenshot showing that User ID.')


async def photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo or not update.effective_user:
        return
    photo = update.message.photo[-1]
    file_id = photo.file_id
    if photo.file_size is not None and photo.file_size > settings.verification_max_photo_bytes:
        await update.message.reply_text('That screenshot is too large. Please send a smaller image.')
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(update.effective_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            return
        if user.onboarding_step == OnboardingStep.PROFILE_PROOF:
            service.set_profile_proof(user, file_id)
            await update.message.reply_text(
                'Profile screenshot saved ✅\n\nNow send your deposit screenshot(s).',
                reply_markup=_button('✅ Finish Verification', 'onboard:submit'),
            )
            return
        if user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try:
                request = service.add_deposit_proof(user, file_id)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
            count = len(request.deposit_proof_file_ids or [])
            await update.message.reply_text(
                f'Deposit screenshot saved ✅ ({count})\n\nSend another if needed, or finish verification.',
                reply_markup=_button('✅ Finish Verification', 'onboard:submit'),
            )

async def admin_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    if not settings.owner_telegram_id or query.from_user.id != settings.owner_telegram_id:
        await query.answer('Not authorized.', show_alert=True)
        return
    try:
        _, action, request_id_text = query.data.split(':', 2)
        request_id = int(request_id_text)
    except (ValueError, AttributeError):
        await query.answer('Invalid admin action.', show_alert=True)
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        try:
            request, user, changed = service.review(request_id, query.from_user.id, action)
        except ValueError as exc:
            await query.answer(str(exc), show_alert=True)
            return
    if not changed:
        await query.answer('Already saved.', show_alert=True)
        return
    await query.answer('Saved')
    await query.edit_message_reply_markup(reply_markup=None)
    if action == 'approve':
        await context.bot.send_message(user.telegram_user_id, 'Verification approved ✅\n\nYour BTC 5s signal access is active.', reply_markup=_approved_menu())
        await query.message.reply_text(f'Approved request #{request.id}.')
    elif action == 'resubmit':
        await context.bot.send_message(user.telegram_user_id, 'Your verification needs new evidence. Send your BC.GAME User ID to begin the new packet.')
        await query.message.reply_text(f'Resubmission requested for #{request.id}.')
    else:
        await context.bot.send_message(user.telegram_user_id, 'Verification was not approved. Please contact support if needed.')
        await query.message.reply_text(f'Rejected request #{request.id}.')


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return

    with SessionLocal() as db:
        onboarding = OnboardingService(db)
        user = onboarding.get_or_create_user(query.from_user)
        if user.status != UserStatus.APPROVED or user.is_blocked:
            await query.answer('Approved access is required.', show_alert=True)
            return

        if query.data == 'menu:home':
            await query.answer()
            await query.message.reply_text('Choose an option:', reply_markup=_approved_menu())
            return

        if query.data == 'menu:signal':
            await query.answer()
            await query.message.reply_text(format_scan_context(), reply_markup=build_scan_prompt_keyboard())
            return

        if query.data == 'menu:scan_now':
            await query.answer('Checking the next BC.GAME round…')
            result = await UserSignalService(db).request_scan(user.id)
            if not result.available:
                await query.message.reply_text(result.reason, reply_markup=build_scan_prompt_keyboard())
                return
            signal = result.signal
            await query.message.reply_text(format_signal(signal), reply_markup=build_signal_keyboard(signal.direction))
            return

        if query.data == 'menu:results':
            await query.answer()
            recent = db.query(Signal).filter(Signal.requested_by_user_id == user.id).order_by(Signal.id.desc()).limit(10).all()
            if not recent:
                await query.message.reply_text('You do not have any signal results yet.', reply_markup=_approved_menu())
                return
            lines = ['📈 MY RECENT 5s SIGNALS', '']
            for signal in recent:
                lines.append(f'#{signal.id}  {signal.direction.value} — {_result_label(signal)}')
            await query.message.reply_text('\n'.join(lines), reply_markup=_approved_menu())
            return

        if query.data == 'menu:help':
            await query.answer()
            await query.message.reply_text(
                'ℹ️ HOW IT WORKS\n\n'
                'BC.GAME accepts UP/DOWN orders during its countdown. When the countdown ends, BC.GAME records the Start Rate at the first flag. Five seconds later it records the End Rate at the second flag.\n\n'
                'UP wins when End Rate is above Start Rate. DOWN wins otherwise according to the game instructions.\n\n'
                'This bot analyzes short-term BTC market pressure and can return UP, DOWN, NO TRADE, or UNAVAILABLE. It does not guarantee outcomes and does not place trades automatically.',
                reply_markup=_approved_menu(),
            )
            return

        if query.data == 'menu:support':
            await query.answer()
            if settings.support_url:
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('🆘 Open Support', url=settings.support_url)]])
                await query.message.reply_text('Need help?', reply_markup=keyboard)
            else:
                await query.message.reply_text('Support contact has not been configured yet.', reply_markup=_approved_menu())
            return

    await query.answer()
