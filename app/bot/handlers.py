from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_signal
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import OnboardingStep, UserStatus
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService

settings = get_settings()

SIGNAL_BUTTON = '⚡ BTC 5s Signal'
HELP_BUTTON = 'ℹ️ How It Works'
SUPPORT_BUTTON = '🆘 Support'


def _button(label: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]])


def _approved_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[SIGNAL_BUTTON], [HELP_BUTTON, SUPPORT_BUTTON]],
        resize_keyboard=True,
        is_persistent=True,
    )


def _is_access_blocked(user) -> bool:
    return bool(user.is_blocked or user.status == UserStatus.SUSPENDED)


async def _run_signal_scan(chat, db, user) -> None:
    result = await UserSignalService(db).request_scan(user.id)
    if not result.available or result.signal is None:
        await chat.send_message(result.reason, reply_markup=build_scan_prompt_keyboard())
        return
    signal = result.signal
    await chat.send_message(
        format_signal(signal),
        reply_markup=build_signal_keyboard(signal.direction, signal.id),
    )


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
        'Enter the amount you want to trade on BC.GAME before requesting a signal. Do not tap UP or DOWN yet.\n\n'
        '3️⃣ WAIT FOR A FRESH ROUND\n'
        'Watch the round timer on BC.GAME and wait for a new order countdown to begin (~15–20s).\n\n'
        '4️⃣ SCAN FOR SIGNAL\n'
        'Watch the countdown on BC.GAME. Tap ⚡ BTC 5s Signal anytime during the countdown (from 15s down to 1s). The closer to start, the sharper the micro-momentum.\n\n'
        '5️⃣ READ THE SIGNAL GUIDANCE\n'
        '🟢 UP — qualified upward expansion setup\n'
        '🔴 DOWN — qualified downward momentum setup\n'
        '⚪ NO TRADE — flat chop or pre-start exhaustion (skip round)\n'
        '🔥 STAKE HIGH — rare 10/10 institutional prime setup (maximum conviction)\n'
        '🛡️ Skip Round — choppy market or counter-trend movement\n\n'
        '6️⃣ PLACE THE TRADE\n'
        'If you receive UP or DOWN, return to BC.GAME and tap that direction immediately before the countdown reaches 0:00.\n\n'
        '7️⃣ RESULT\n'
        'At 0:00, BCGAME records the Start Rate. Five seconds later it records the End Rate.\n\n'
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
                '⚡ WELCOME TO BCGAME AI SIGNALS 🇳🇬\n\n'
                'Get institutional-grade BTC/USD 5-second Up/Down trading signals directly inside Telegram.\n\n'
                '🔥 EXCLUSIVE ACCESS TIERS (DEPOSIT IN NAIRA):\n'
                '🥉 Starter Tier — ₦15,000 deposit\n'
                '• 3 to 4 High-Accuracy Scans / Day\n'
                '• Minimum qualifying deposit to unlock access\n\n'
                '🥈 Pro Trader Tier — ₦20,000 to ₦49,000 deposit (⭐ Most Popular)\n'
                '• 5 to 8 High-Accuracy Scans / Day\n'
                '• Fast-momentum setups & Stake Guidance\n\n'
                '🥇 VIP Elite Tier — ₦50,000 to ₦100,000+ deposit\n'
                '• Unlimited Daily Signal Scans\n'
                '• Prime Institutional Signals (Stake High setups)\n'
                '• Priority VIP Approval & Fast-Track Access\n\n'
                '━━━━━━━━━━━━━━━━━━━━━\n'
                '1️⃣ CREATE YOUR ACCOUNT\n'
                'Tap the button below to register your BCGAME account. Once registered, return here and tap “✅ I Have Registered”.',
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return
        if step == OnboardingStep.DEPOSIT:
            request = service.current_request(user)
            chosen_key = None
            if request.admin_note:
                for k, v in TIER_INFO.items():
                    if v['name'] == request.admin_note:
                        chosen_key = k
                        break
            await _send_deposit_step(update, tier_key=chosen_key, edit=False)
            return
        if step == OnboardingStep.BC_ID:
            await update.effective_chat.send_message('3️⃣ SEND YOUR BCGAME USER ID 🆔\n\nCopy your User ID from your BCGAME profile and send it here.')
            return
        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('4️⃣ PROFILE SCREENSHOT 📸\n\nSend one clear screenshot of your BCGAME profile showing the User ID you submitted.')
            return
        if step == OnboardingStep.DEPOSIT_PROOF:
            request = service.current_request(user)
            proof_count = len(request.deposit_proof_file_ids or [])
            tier_line = f'⭐ Selected Tier: {request.admin_note}\n\n' if request.admin_note else ''
            deposit_req = request.admin_note or '₦15,000 or more'
            if proof_count:
                await update.effective_chat.send_message(
                    f'5️⃣ DEPOSIT PROOF 🧾\n\n'
                    f'✅ {proof_count} deposit screenshot(s) received.\n\n'
                    f'{tier_line}'
                    f'💰 Target deposit: {deposit_req}\n\n'
                    'Tap below to submit for verification, or send another screenshot if needed.',
                    reply_markup=_button('✅ Submit Verification', 'onboard:submit'),
                )
            else:
                await update.effective_chat.send_message(
                    f'5️⃣ DEPOSIT PROOF 🧾\n\n'
                    f'{tier_line}'
                    f'Send one clear screenshot showing your BCGAME deposit ({deposit_req}).\n\n'
                    'The submit button will appear once your screenshot is received.'
                )
            return
        if step == OnboardingStep.REVIEW:
            await update.effective_chat.send_message('⏳ VERIFICATION UNDER REVIEW\n\nYour evidence has been submitted. You will receive a message here once your access is approved.')
            return
        if step == OnboardingStep.RESUBMIT:
            await update.effective_chat.send_message('🔄 NEW VERIFICATION REQUESTED\n\nSend your BCGAME User ID to begin again.')


TIER_INFO = {
    'starter': {
        'name': '🥉 Starter Tier (₦15,000)',
        'amount': '₦15,000',
        'scans': '3 to 4 High-Accuracy Scans / Day',
        'perks': 'Minimum qualifying deposit to unlock access',
    },
    'pro': {
        'name': '🥈 Pro Trader Tier (₦20,000 – ₦49,000)',
        'amount': '₦20,000 or more',
        'scans': '5 to 8 High-Accuracy Scans / Day (⭐ Most Popular)',
        'perks': 'Micro-momentum setups & Stake Guidance',
    },
    'vip': {
        'name': '🥇 VIP Elite Tier (₦50,000 – ₦100,000+)',
        'amount': '₦50,000 or more',
        'scans': 'Unlimited Daily Signal Scans',
        'perks': 'Prime Institutional Signals & Priority VIP Approval',
    },
}


def _deposit_tiers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🥉 Starter Tier (₦15,000) • 3–4 Scans', callback_data='onboard:tier:starter')],
        [InlineKeyboardButton('🥈 Pro Trader Tier (₦20,000+) • 5–8 Scans ⭐', callback_data='onboard:tier:pro')],
        [InlineKeyboardButton('🥇 VIP Elite Tier (₦50,000+) • Unlimited', callback_data='onboard:tier:vip')],
    ])


def _tier_deposit_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    if settings.bcgame_deposit_url:
        keyboard.append([InlineKeyboardButton('💳 Open BCGAME Deposit', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('✅ I Have Deposited', callback_data='onboard:deposited')])
    keyboard.append([InlineKeyboardButton('🔄 Choose Different Tier', callback_data='onboard:tier:choose')])
    return InlineKeyboardMarkup(keyboard)


async def _send_deposit_step(update: Update, tier_key: str | None = None, edit: bool = False):
    chat = update.effective_chat
    if tier_key and tier_key in TIER_INFO:
        info = TIER_INFO[tier_key]
        text = (
            f'🎯 TIER SELECTED: {info["name"]}\n\n'
            f'• Daily Signals: {info["scans"]}\n'
            f'• Features: {info["perks"]}\n\n'
            '💳 PROCEED TO DEPOSIT:\n'
            '1. Tap "💳 Open BCGAME Deposit" below.\n'
            '2. Select Naira (Bank Transfer, OPay, Palmpay, Card, or Crypto).\n'
            f'3. Complete your deposit of {info["amount"]} on BCGAME.\n'
            '4. Save a screenshot of your successful transaction receipt.\n\n'
            'Once completed, return here and tap “✅ I Have Deposited”.'
        )
        markup = _tier_deposit_keyboard()
    else:
        text = (
            '2️⃣ SELECT YOUR TRADING TIER (NAIRA) 💳\n\n'
            'Tap the button for the tier you want to activate:\n\n'
            '🥉 STARTER TIER — ₦15,000\n'
            '• 3–4 High-Accuracy Scans Daily\n'
            '• Minimum qualifying deposit\n\n'
            '🥈 PRO TRADER TIER — ₦20,000 to ₦49,000 (⭐ Most Popular)\n'
            '• 5–8 High-Accuracy Scans Daily\n'
            '• Micro-Momentum Setups & Stake Guidance\n\n'
            '🥇 VIP ELITE TIER — ₦50,000 to ₦100,000+\n'
            '• Unlimited Daily Signal Scans\n'
            '• Prime Institutional Signals (Stake High setups)\n'
            '• Priority VIP Approval & Fast-Track Access\n\n'
            '👇 Tap your preferred tier below to proceed:'
        )
        markup = _deposit_tiers_keyboard()

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=markup)
    elif chat:
        await chat.send_message(text, reply_markup=markup)


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
        if query.data.startswith('onboard:tier:'):
            tier_action = query.data.split(':', 2)[2]
            if tier_action == 'choose':
                await query.answer()
                await _send_deposit_step(update, tier_key=None, edit=True)
                return
            if tier_action in TIER_INFO:
                await query.answer(f'Selected {TIER_INFO[tier_action]["name"]}')
                service.set_selected_tier(user, TIER_INFO[tier_action]['name'])
                await _send_deposit_step(update, tier_key=tier_action, edit=True)
                return
        if query.data == 'onboard:registered' and user.onboarding_step == OnboardingStep.REGISTRATION:
            await query.answer()
            service.set_step(user, OnboardingStep.DEPOSIT)
            await query.edit_message_text('✅ Registration step complete.')
            await _send_deposit_step(update, edit=False)
            return
        if query.data == 'onboard:deposited' and user.onboarding_step == OnboardingStep.DEPOSIT:
            await query.answer()
            service.set_step(user, OnboardingStep.BC_ID)
            await query.edit_message_text('✅ Deposit step completed.\n\n3️⃣ SEND YOUR BCGAME USER ID 🆔\n\nCopy your numeric User ID from your BCGAME profile and send it here.')
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
                await _run_signal_scan(update.effective_chat, db, user)
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
            request = service.current_request(user)
            deposit_prompt = f' ({request.admin_note})' if request.admin_note else ' of ₦15,000 or more'
            await update.message.reply_text(
                '✅ PROFILE SCREENSHOT RECEIVED 📸\n\n'
                '5️⃣ DEPOSIT PROOF 🧾\n\n'
                f'Now send a clear screenshot showing your BCGAME deposit{deposit_prompt}.'
            )
            return
        if user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try:
                request = service.add_deposit_proof(user, file_id)
            except ValueError as exc:
                await update.message.reply_text(str(exc))
                return
            count = len(request.deposit_proof_file_ids or [])
            tier_line = f'⭐ Selected Tier: {request.admin_note}\n\n' if request.admin_note else ''
            await update.message.reply_text(
                f'✅ DEPOSIT PROOF RECEIVED ({count}) 🧾\n\n'
                f'{tier_line}'
                'Everything required is ready! Tap below to submit your verification for review.',
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
        if query.data in {'menu:signal', 'menu:scan_now'}:
            await query.answer('Scanning live BTC market…')
            await _run_signal_scan(query.message.chat, db, user)
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
