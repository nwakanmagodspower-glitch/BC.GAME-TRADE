from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_scan_context, format_signal
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import OnboardingStep, Signal, UserStatus
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService

settings = get_settings()

SIGNAL_BUTTON = '⚡ BTC 5s Signal'
RESULTS_BUTTON = '📈 My Results'
HELP_BUTTON = 'ℹ️ How It Works'
SUPPORT_BUTTON = '🆘 Support'


def _button(label: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]])


def _approved_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[SIGNAL_BUTTON, RESULTS_BUTTON], [HELP_BUTTON, SUPPORT_BUTTON]],
        resize_keyboard=True,
        is_persistent=True,
    )


def _is_access_blocked(user) -> bool:
    return bool(user.is_blocked or user.status == UserStatus.SUSPENDED)


def _result_label(signal: Signal) -> str:
    source = str(((signal.features_snapshot or {}).get('_bcgame_round') or {}).get('source') or '')
    if source == 'MANUAL_SYNC' and signal.status.value in {'WIN', 'LOSS', 'TIE'}:
        return f'{signal.status.value} (external reference only)'
    if signal.status.value == 'EXPIRED':
        return 'UNRESOLVED'
    return signal.status.value


async def _send_results(chat, db, user) -> None:
    recent = db.query(Signal).filter(Signal.requested_by_user_id == user.id).order_by(Signal.id.desc()).limit(10).all()
    if not recent:
        await chat.send_message('📈 MY RESULTS\n\nNo recent signals yet. Your latest results will appear here after you start scanning.')
        return
    lines = ['📈 MY RECENT SIGNALS', 'Latest 10 • automatically cleared after 10 days', '']
    for signal in recent:
        lines.append(f'#{signal.id}  {signal.direction.value} — {_result_label(signal)}')
    await chat.send_message('\n'.join(lines))


async def _send_help(chat) -> None:
    await chat.send_message(
        'ℹ️ HOW IT WORKS\n\n'
        '⚡ BCGAME BTC/USD — 5 SECOND UP/DOWN\n\n'
        '1️⃣ SET UP THE CORRECT MARKET\n'
        'Open BCGAME Up/Down and select:\n'
        '• Pair: BTC/USD\n'
        '• Duration: 5 Seconds\n'
        '• Range: $1–$50\n\n'
        'This system is built specifically for the 5s • $1–$50 Up/Down market. Do not use its signals on the other 5-second ranges.\n\n'
        '2️⃣ ENTER YOUR TRADE AMOUNT\n'
        'Enter the amount you want to trade before requesting a signal. Do not tap UP or DOWN yet.\n\n'
        '3️⃣ WATCH THE 15-SECOND COUNTDOWN\n'
        'Wait for a fresh round. When the order window begins, BCGAME counts down from 15 seconds.\n\n'
        '4️⃣ SCAN EARLY\n'
        'When BCGAME shows 15, 14, 13 or 12 seconds, return to the bot and tap the exact matching countdown button immediately.\n\n'
        '5️⃣ READ THE SIGNAL\n'
        '🟢 UP — upward setup detected\n'
        '🔴 DOWN — downward setup detected\n'
        '⚪ NO TRADE — setup is not strong enough\n'
        '⚠️ UNAVAILABLE — timing or market data is not safe enough\n\n'
        '6️⃣ PLACE THE TRADE\n'
        'If you receive UP or DOWN with enough time remaining, return to BCGAME and tap the same direction before the countdown reaches 0. If you are late, skip the round.\n\n'
        '7️⃣ RESULT\n'
        'At 0, BCGAME records the Start Rate. Five seconds later it records the End Rate.\n\n'
        'End Rate > Start Rate → UP wins\n'
        'End Rate ≤ Start Rate → DOWN wins'
    )


async def _send_support(chat) -> None:
    if settings.support_url:
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton('🆘 Open Support', url=settings.support_url)]])
        await chat.send_message('🆘 NEED HELP?\n\nTap below to contact support.', reply_markup=keyboard)
    else:
        await chat.send_message('🆘 Support is not configured yet.')


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
            await update.effective_chat.send_message('⚡ BCGAME AI SIGNALS\n\n✅ Access active. Choose what you want to do below.', reply_markup=_approved_menu())
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
                keyboard.append([InlineKeyboardButton('🔗 Create BCGAME Account', url=settings.bcgame_registration_url)])
            keyboard.append([InlineKeyboardButton('✅ I Have Registered', callback_data='onboard:registered')])
            await update.effective_chat.send_message(
                '⚡ WELCOME TO BCGAME AI SIGNALS\n\n'
                'Get BTC/USD 5-second Up/Down signals directly inside Telegram.\n\n'
                '🔐 PRIVATE ACCESS\n'
                'To qualify, register through our link and make a deposit of $10 or more.\n\n'
                '1️⃣ CREATE YOUR ACCOUNT\n'
                'Tap the button below to register. Once your account is ready, come back and tap “I Have Registered”.',
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        if step == OnboardingStep.DEPOSIT:
            await _send_deposit_step(update)
            return
        if step == OnboardingStep.BC_ID:
            await update.effective_chat.send_message('3️⃣ SEND YOUR BCGAME USER ID\n\nCopy your User ID from your BCGAME profile and send it here.')
            return
        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('4️⃣ PROFILE SCREENSHOT\n\nSend one clear screenshot of your BCGAME profile showing the User ID you submitted.')
            return
        if step == OnboardingStep.DEPOSIT_PROOF:
            request = service.current_request(user)
            proof_count = len(request.deposit_proof_file_ids or [])
            if proof_count:
                await update.effective_chat.send_message(
                    f'5️⃣ DEPOSIT PROOF\n\n✅ {proof_count} deposit screenshot(s) received.\n\nMinimum qualifying deposit: $10 or more.\n\nSubmit now or add another screenshot if needed.',
                    reply_markup=_button('✅ Submit Verification', 'onboard:submit'),
                )
            else:
                await update.effective_chat.send_message(
                    '5️⃣ DEPOSIT PROOF\n\nSend one clear screenshot showing your BCGAME deposit of $10 or more. The submit button will appear after it is received.'
                )
            return
        if step == OnboardingStep.REVIEW:
            await update.effective_chat.send_message('⏳ VERIFICATION UNDER REVIEW\n\nYour evidence has been submitted. You will receive a message here once your access is approved.')
            return
        if step == OnboardingStep.RESUBMIT:
            await update.effective_chat.send_message('🔄 NEW VERIFICATION REQUESTED\n\nSend your BCGAME User ID to begin again.')


async def _send_deposit_step(update: Update):
    keyboard = []
    if settings.bcgame_deposit_url:
        keyboard.append([InlineKeyboardButton('💳 Open BCGAME Deposit', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('✅ I Have Deposited', callback_data='onboard:deposited')])
    await update.effective_chat.send_message(
        '2️⃣ FUND YOUR ACCOUNT\n\n'
        '💰 Minimum qualifying deposit: $10 or more.\n\n'
        'Make your deposit on BCGAME using the button below. Once completed, return here and tap “I Have Deposited”.',
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(query.from_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            await query.answer('This onboarding action is not available.', show_alert=True)
            return
        if query.data == 'onboard:registered' and user.onboarding_step == OnboardingStep.REGISTRATION:
            await query.answer()
            service.set_step(user, OnboardingStep.DEPOSIT)
            await query.edit_message_text('✅ Registration step complete.')
            await _send_deposit_step(update)
            return
        if query.data == 'onboard:deposited' and user.onboarding_step == OnboardingStep.DEPOSIT:
            await query.answer()
            service.set_step(user, OnboardingStep.BC_ID)
            await query.edit_message_text('✅ Deposit step complete.\n\n3️⃣ SEND YOUR BCGAME USER ID\n\nCopy your User ID from your BCGAME profile and send it here.')
            return
        if query.data == 'onboard:submit' and user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try:
                service.submit(user)
            except ValueError as exc:
                message = str(exc)
                if message == 'Verification packet is incomplete':
                    message = 'Please send at least one deposit screenshot before submitting.'
                await query.answer(message, show_alert=True)
                return
            await query.answer('Verification submitted ✅')
            await query.edit_message_text('✅ VERIFICATION SUBMITTED\n\nYour evidence has been sent for review. You will receive a message here as soon as your access is approved.')
            return
        await query.answer('That step is no longer active.', show_alert=True)


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user:
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(update.effective_user)
        if user.status == UserStatus.APPROVED and not user.is_blocked:
            text = update.message.text.strip()
            if text == SIGNAL_BUTTON:
                await update.message.reply_text(format_scan_context(), reply_markup=build_scan_prompt_keyboard())
            elif text == RESULTS_BUTTON:
                await _send_results(update.effective_chat, db, user)
            elif text == HELP_BUTTON:
                await _send_help(update.effective_chat)
            elif text == SUPPORT_BUTTON:
                await _send_support(update.effective_chat)
            return
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            return
        if user.onboarding_step == OnboardingStep.BC_ID:
            value = update.message.text.strip()
            if len(value) < 2 or len(value) > 255:
                await update.message.reply_text('Please send a valid BCGAME User ID.')
                return
            service.set_bcgame_user_id(user, value)
            await update.message.reply_text('✅ USER ID RECEIVED\n\n4️⃣ PROFILE SCREENSHOT\n\nNow send one clear screenshot of your BCGAME profile showing that User ID.')


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
                '✅ PROFILE SCREENSHOT RECEIVED\n\n'
                '5️⃣ DEPOSIT PROOF\n\n'
                'Now send one clear screenshot showing your BCGAME deposit of $10 or more.'
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
                f'✅ DEPOSIT PROOF RECEIVED ({count})\n\nMinimum qualifying deposit: $10 or more.\n\nEverything required is ready. Tap below to send your verification for review.',
                reply_markup=_button('✅ Submit Verification', 'onboard:submit'),
            )


async def admin_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    if (not settings.owner_telegram_id or query.from_user.id != settings.owner_telegram_id or not update.effective_chat or update.effective_chat.type != 'private' or update.effective_chat.id != settings.owner_telegram_id):
        await query.answer('Owner review is available only in the owner private chat.', show_alert=True)
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
        await context.bot.send_message(user.telegram_user_id, '✅ VERIFICATION APPROVED\n\nYour BTC 5s signal access is now active. Choose an option below to begin.', reply_markup=_approved_menu())
        await query.message.reply_text(f'✅ Request #{request.id} approved.')
    elif action == 'resubmit':
        await context.bot.send_message(user.telegram_user_id, '🔄 NEW EVIDENCE NEEDED\n\nPlease send your BCGAME User ID again to start a fresh verification packet.')
        await query.message.reply_text(f'🔄 Resubmission requested for #{request.id}.')
    else:
        await context.bot.send_message(user.telegram_user_id, '❌ Verification was not approved. Please contact support if you need help.')
        await query.message.reply_text(f'❌ Request #{request.id} rejected.')


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
            await query.message.reply_text('Choose an option below.', reply_markup=_approved_menu())
            return
        if query.data == 'menu:signal':
            await query.answer()
            await query.message.reply_text(format_scan_context(), reply_markup=build_scan_prompt_keyboard())
            return
        if query.data == 'menu:scan_now':
            await query.answer('Checking the next BCGAME round…')
            result = await UserSignalService(db).request_scan(user.id)
            if not result.available:
                await query.message.reply_text(result.reason, reply_markup=build_scan_prompt_keyboard())
                return
            signal = result.signal
            await query.message.reply_text(format_signal(signal), reply_markup=build_signal_keyboard(signal.direction))
            return
        if query.data == 'menu:results':
            await query.answer()
            await _send_results(query.message.chat, db, user)
            return
        if query.data == 'menu:help':
            await query.answer()
            await _send_help(query.message.chat)
            return
        if query.data == 'menu:support':
            await query.answer()
            await _send_support(query.message.chat)
            return
    await query.answer()