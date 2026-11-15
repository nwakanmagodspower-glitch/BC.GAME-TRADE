from sqlalchemy import select
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_signal
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import OnboardingStep, User, UserStatus
from app.services.admin_ops import AdminOpsService
from app.services.meta_capi import meta_capi_service
from app.services.onboarding import OnboardingService
from app.services.user_signals import UserSignalService

settings = get_settings()

SIGNAL_BUTTON = '⚡ BTC 5s Signal'
HELP_BUTTON = 'ℹ️ How It Works'
SUPPORT_BUTTON = '🆘 Support'

LOCKED_TERMINAL_TEXT = (
    'See Today’s Live Profits Before You Trade 🇳🇬\n\n'
    'Before you risk a single kobo or touch the bot, step inside our official VIP community.\n\n'
    'Here is what is happening inside right now:\n'
    '• 💰 Live Results & Payouts — Real screenshots of daily winning trades, bank withdrawal alerts, and member testimonials.\n'
    '• 📈 Today’s 5-Second Signals — See the exact winning trades our AI predicted this morning (95%+ accuracy).\n'
    '• 🎥 Live Video Demonstrations — Watch how members take 5-second trades step-by-step.\n\n'
    '👇 Tap below to step inside. Your AI Scanner Terminal will automatically activate the second you join!'
)


def _channel_locked_keyboard() -> InlineKeyboardMarkup:
    invite_link = settings.telegram_channel_invite_link
    if not invite_link and settings.telegram_channel_id:
        ch = str(settings.telegram_channel_id)
        if ch.startswith('@'):
            invite_link = f"https://t.me/{ch[1:]}"
    if not invite_link:
        invite_link = "https://t.me"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📢 Enter Official VIP Community', url=invite_link)]
    ])


async def check_channel_membership(bot, user_id: int) -> bool:
    """Verify if the user is a member, administrator, or creator of CHANNEL_ID.

    Returns True if channel_id is unconfigured, bot is None, or user is owner.
    """
    if not settings.telegram_channel_id or bot is None:
        return True
    if settings.owner_telegram_id and user_id == settings.owner_telegram_id:
        return True
    try:
        member = await bot.get_chat_member(chat_id=settings.telegram_channel_id, user_id=user_id)
        status = getattr(member, 'status', None)
        if status in ('member', 'administrator', 'creator'):
            return True
        if status == 'restricted' and getattr(member, 'is_member', False):
            return True
        return False
    except Exception:
        return False


async def send_onboarding_welcome(bot, chat_id: int, user, db):
    welcome_video = (
        AdminOpsService(db).get_setting(AdminOpsService.WELCOME_VIDEO_KEY, settings.welcome_video_file_id)
        or settings.welcome_video_url
    )
    if welcome_video and hasattr(bot, 'send_video'):
        try:
            try:
                await bot.send_video(
                    chat_id=chat_id,
                    video=welcome_video,
                    caption='🎥 Watch this 1-minute video to see how to start making daily profits with our 5-second Bitcoin signals on BCGAME!',
                )
            except TypeError:
                await bot.send_video(
                    video=welcome_video,
                    caption='🎥 Watch this 1-minute video to see how to start making daily profits with our 5-second Bitcoin signals on BCGAME!',
                )
        except Exception:
            pass

    first_name = getattr(user, 'first_name', None) or 'Trader'
    keyboard = [
        [InlineKeyboardButton('🎯 ₦10,000 / day', callback_data='onboard:goal:10k')],
        [InlineKeyboardButton('🎯 ₦25,000 / day', callback_data='onboard:goal:25k')],
        [InlineKeyboardButton('🎯 ₦50,000+ / day', callback_data='onboard:goal:50k')],
    ]

    text = (
        f'👋 Welcome {first_name}! 🇳🇬\n\n'
        'Standard VIP access costs ₦50,000/month, but you can claim a 100% Free VIP Trial today.\n\n'
        '💡 YOUR MONEY STAYS IN YOUR CONTROL:\n'
        'You do NOT pay any bot subscription fees until you test and confirm its profitability for yourself. '
        'Your deposit remains 100% in your personal BCGAME account — trade with it and withdraw your profits to your Nigerian bank account anytime.\n\n'
        '━━━━━━━━━━━━━━━━━━━━━\n'
        '🎯 Step 1: What is your daily profit goal?'
    )
    markup = InlineKeyboardMarkup(keyboard)
    if hasattr(bot, 'send_message'):
        try:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
        except TypeError:
            await bot.send_message(text=text, reply_markup=markup)


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
        '1️⃣ CHOOSE YOUR STAKE ROOM\n'
        'Open BCGAME Up/Down and select any room of your choice:\n'
        '• $1–$50\n'
        '• $50–$100\n'
        '• $100–$200+\n\n'
        '💡 The signal works universally across ALL rooms because every room shares the exact same 5-second Bitcoin chart, Start Rate, and End Rate!\n\n'
        '2️⃣ WAIT FOR A FRESH ROUND\n'
        'Watch the round timer on BC.GAME and wait for a new order countdown to begin (~15–20s).\n\n'
        '3️⃣ SCAN FOR SIGNAL\n'
        'Watch the countdown on BC.GAME. Tap ⚡ BTC 5s Signal when the countdown is between 8s to 12s remaining for maximum comfort and accuracy.\n\n'
        '4️⃣ READ THE SIGNAL GUIDE\n'
        '🟢 UP — Strong upward move\n'
        '🔴 DOWN — Strong downward move\n'
        '⚪ NO TRADE — Flat or sideways market (skip round)\n\n'
        '5️⃣ PLACE THE TRADE\n'
        'If you receive UP or DOWN, return to BC.GAME and tap that direction immediately before the countdown reaches 0:00.\n\n'
        '6️⃣ RESULT\n'
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
    args = getattr(context, 'args', None) or []
    raw_start_arg = args[0] if args else ''
    start_arg = raw_start_arg.lower()
    is_vip = start_arg in {'vip', 'direct', 'fasttrack'}

    fbclid = None
    if raw_start_arg:
        if start_arg.startswith('fbclid_'):
            fbclid = raw_start_arg[7:]
        elif 'fbclid=' in start_arg:
            parts = raw_start_arg.split('fbclid=')
            fbclid = parts[1].split('&')[0]
        elif start_arg.startswith('fb_'):
            fbclid = raw_start_arg
        elif len(raw_start_arg) > 10 and not is_vip:
            fbclid = raw_start_arg

    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(tg_user, fbclid=fbclid)
        if user.is_blocked:
            await update.effective_chat.send_message('Your access is blocked. Please contact support.')
            return

        is_channel_ok = await check_channel_membership(getattr(context, 'bot', None), tg_user.id)
        if not is_channel_ok:
            await update.effective_chat.send_message(
                LOCKED_TERMINAL_TEXT,
                reply_markup=_channel_locked_keyboard(),
            )
            return

        if user.funnel_step in ('1_STARTED', None):
            service.set_funnel_step(user, '2_CHANNEL_JOINED')
            await meta_capi_service.send_lead_event(user)

        # Direct VIP fast-track for leads registered via the owner (?start=vip)
        if is_vip and user.status != UserStatus.APPROVED:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            user.status = UserStatus.APPROVED
            user.onboarding_step = OnboardingStep.APPROVED
            user.funnel_step = '4_VIP_APPROVED'
            user.step_updated_at = now
            user.approved_at = now
            user.approved_by = settings.owner_telegram_id
            db.commit()
            db.refresh(user)
            await meta_capi_service.send_purchase_event(user, amount_ngn=50000.0, tier_name='VIP Fast-Track')
            if settings.owner_telegram_id:
                try:
                    await context.bot.send_message(
                        settings.owner_telegram_id,
                        f'🌟 NEW VIP LEAD AUTO-APPROVED!\n\n'
                        f'• Name: {tg_user.first_name}\n'
                        f'• Username: @{tg_user.username or "None"}\n'
                        f'• ID: {tg_user.id}\n'
                        f'• Access: Instant VIP Access via direct link (?start={start_arg})',
                    )
                except Exception:
                    pass

        if user.status == UserStatus.APPROVED:
            welcome_text = (
                '⚡ BCGAME AI SIGNALS — VIP ACCESS\n\n'
                f'👋 Welcome {tg_user.first_name or "Trader"}!\n'
                '✅ Access active! Choose what you want to do below.\n\n'
                '🎯 Universal Signals: Works on ALL rooms ($1–$50, $50–$100, $100–$200+).'
            )
            await update.effective_chat.send_message(welcome_text, reply_markup=_approved_menu())
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
            target_chat_id = getattr(update.effective_chat, 'id', getattr(tg_user, 'id', 0))
            await send_onboarding_welcome(getattr(context, 'bot', None) or update.effective_chat, target_chat_id, tg_user, db)
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
            await update.effective_chat.send_message(
                '3️⃣ SEND YOUR BCGAME USER ID 🆔\n\n'
                '📍 Where to find it:\n'
                '1. Open BCGAME\n'
                '2. Tap the Profile icon at the top right\n'
                '3. Copy the numeric User ID displayed under your username (e.g. 12345678)\n\n'
                'Send your numeric User ID here to continue.'
            )
            return
        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('4️⃣ PROFILE SCREENSHOT 📸\n\nSend one clear screenshot of your BCGAME profile showing the User ID you submitted.')
            return
        if step == OnboardingStep.DEPOSIT_PROOF:
            request = service.current_request(user)
            proof_count = len(request.deposit_proof_file_ids or [])
            tier_line = f'⭐ Selected Tier: {request.admin_note}\n\n' if request.admin_note else ''
            deposit_req = request.admin_note or '₦5,000 or more'
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
            await update.effective_chat.send_message(
                '🔄 NEW VERIFICATION REQUESTED\n\n'
                'Send your numeric BCGAME User ID to begin again (found under Profile icon at top right).'
            )


TIER_INFO = {
    'starter': {
        'name': '🥉 Starter (₦5,000 – ₦15,000)',
        'amount': '₦5,000 – ₦15,000',
        'trial': '7 Days',
        'scans': '3 to 4 Scans Daily',
        'daily_profit': '₦6,000 – ₦12,000+',
        'trial_profit': '₦40,000 – ₦80,000+',
    },
    'pro': {
        'name': '🥈 Pro (₦15,000 – ₦35,000)',
        'amount': '₦15,000 – ₦35,000',
        'trial': '14 Days',
        'scans': '5 to 8 Scans Daily',
        'daily_profit': '₦15,000 – ₦30,000+',
        'trial_profit': '₦150,000 – ₦300,000+',
    },
    'vip': {
        'name': '🥇 VIP (₦35,000 – ₦100,000+)',
        'amount': '₦35,000 – ₦100,000+',
        'trial': '30 Days',
        'scans': 'Unlimited Scans Daily',
        'daily_profit': '₦40,000 – ₦80,000+',
        'trial_profit': '₦500,000+',
    },
}


def _deposit_tiers_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('🥉 Starter (₦5,000 – ₦15,000)', callback_data='onboard:tier:starter')],
        [InlineKeyboardButton('🥈 Pro (₦15,000 – ₦35,000)', callback_data='onboard:tier:pro')],
        [InlineKeyboardButton('🥇 VIP (₦35,000 – ₦100,000+)', callback_data='onboard:tier:vip')],
    ])


def _tier_deposit_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    if settings.bcgame_deposit_url:
        keyboard.append([InlineKeyboardButton('💳 Open BCGAME Deposit', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('✅ I Have Registered & Deposited', callback_data='onboard:deposited')])
    keyboard.append([InlineKeyboardButton('🔄 Choose Different Level', callback_data='onboard:tier:choose')])
    return InlineKeyboardMarkup(keyboard)


async def _send_deposit_step(update: Update, tier_key: str | None = None, edit: bool = False):
    chat = update.effective_chat
    if tier_key and tier_key in TIER_INFO:
        info = TIER_INFO[tier_key]
        first_name = (update.effective_user.first_name if update.effective_user else None) or 'Trader'
        reg_url = settings.bcgame_registration_url
        if tier_key == 'starter' and settings.bcgame_registration_url_starter:
            reg_url = settings.bcgame_registration_url_starter
        elif tier_key in ('pro', 'vip') and settings.bcgame_registration_url_vip:
            reg_url = settings.bcgame_registration_url_vip

        keyboard = []
        if reg_url:
            keyboard.append([InlineKeyboardButton('🔗 Create BCGAME Account', url=reg_url)])
        if settings.bcgame_deposit_url:
            keyboard.append([InlineKeyboardButton('💳 Open BCGAME Deposit', url=settings.bcgame_deposit_url)])
        keyboard.append([InlineKeyboardButton('✅ I Have Registered & Deposited', callback_data='onboard:deposited')])
        keyboard.append([InlineKeyboardButton('🔄 Choose Different Level', callback_data='onboard:tier:choose')])

        text = (
            '🎟️ VIP ACCESS RESERVATION APPROVED!\n\n'
            f'👤 Trader: {first_name}\n'
            f'⭐ Selected Level: {info["name"]}\n'
            f'💰 Recommended Deposit: {info["amount"]}\n'
            f'⏱️ Trial Access: {info["trial"]}\n'
            f'⚡ Signals Included: {info["scans"]}\n'
            f'📈 Target Profit: {info["trial_profit"]} (covers future renewals from profit!)\n\n'
            '━━━━━━━━━━━━━━━━━━━━━\n'
            '👇 ACTIVATE IN 2 SIMPLE STEPS:\n\n'
            '1️⃣ Tap “🔗 Create BCGAME Account” below to register and automatically link your account.\n'
            f'2️⃣ Fund your balance ({info["amount"]}), then tap “✅ I Have Registered & Deposited” below to submit your User ID.'
        )
        markup = InlineKeyboardMarkup(keyboard)
    else:
        text = (
            '💳 Step 3: Choose your starting deposit level:\n\n'
            'Select the amount you want to start with to fund your BCGAME account, activate your trial signals, and start profiting today:\n\n'
            '🔒 100% Secure: We never ask for passwords or account access. Your deposit stays in your wallet for trading and withdrawals.'
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
    if not await check_channel_membership(getattr(context, 'bot', None), query.from_user.id):
        await query.answer('Channel membership required.', show_alert=True)
        await query.message.reply_text(
            LOCKED_TERMINAL_TEXT,
            reply_markup=_channel_locked_keyboard(),
        )
        return
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(query.from_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            await query.answer('This onboarding action is not available.', show_alert=True)
            return

        if query.data.startswith('onboard:goal:'):
            goal_key = query.data.split(':', 2)[2]
            goal_labels = {'10k': '₦10,000 / day', '25k': '₦25,000 / day', '50k': '₦50,000+ / day'}
            chosen_goal = goal_labels.get(goal_key, '₦10,000 / day')
            await query.answer()
            await query.edit_message_text(
                f'🎯 Target Set: {chosen_goal}\n\n'
                '📊 Step 2: What is your trading experience level?',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('🟢 Beginner', callback_data=f'onboard:exp:beg:{goal_key}')],
                    [InlineKeyboardButton('🟡 Intermediate', callback_data=f'onboard:exp:int:{goal_key}')],
                    [InlineKeyboardButton('🔴 Experienced', callback_data=f'onboard:exp:exp:{goal_key}')],
                ]),
            )
            return

        if query.data.startswith('onboard:exp:'):
            await query.answer()
            text = (
                '💳 Step 3: Choose your starting deposit level:\n\n'
                'Select the amount you want to start with to fund your BCGAME account, activate your trial signals, and start profiting today:\n\n'
                '🔒 100% Secure: We never ask for passwords or account access. Your deposit stays in your wallet for trading and withdrawals.'
            )
            await query.edit_message_text(text, reply_markup=_deposit_tiers_keyboard())
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
                service.set_step(user, OnboardingStep.DEPOSIT)
                await _send_deposit_step(update, tier_key=tier_action, edit=True)
                return
        if query.data in ('onboard:registered', 'onboard:deposited') and user.onboarding_step in (OnboardingStep.REGISTRATION, OnboardingStep.DEPOSIT):
            await query.answer()
            service.set_step(user, OnboardingStep.BC_ID)
            await query.edit_message_text(
                '✅ Account setup completed.\n\n'
                '3️⃣ SEND YOUR BCGAME USER ID 🆔\n\n'
                '📍 Where to find it:\n'
                '1. Open BCGAME\n'
                '2. Tap the Profile icon at the top right\n'
                '3. Copy the numeric User ID displayed under your username (e.g. 12345678)\n\n'
                'Send your numeric User ID here to continue.'
            )
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
    if not await check_channel_membership(getattr(context, 'bot', None), update.effective_user.id):
        await update.message.reply_text(
            LOCKED_TERMINAL_TEXT,
            reply_markup=_channel_locked_keyboard(),
        )
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
            await meta_capi_service.send_registration_event(user, bcgame_id=value)
            await update.message.reply_text('✅ USER ID RECEIVED\n\n4️⃣ PROFILE SCREENSHOT\n\nNow send one clear screenshot of your BCGAME profile showing that User ID.')


async def photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo or not update.effective_user:
        return
    if not await check_channel_membership(getattr(context, 'bot', None), update.effective_user.id):
        await update.message.reply_text(
            LOCKED_TERMINAL_TEXT,
            reply_markup=_channel_locked_keyboard(),
        )
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
        amount = 25000.0
        if request.admin_note:
            if 'Starter' in request.admin_note or '5,000' in request.admin_note:
                amount = 10000.0
            elif 'VIP' in request.admin_note or '100,000' in request.admin_note or '35,000' in request.admin_note:
                amount = 50000.0
            elif 'Pro' in request.admin_note or '15,000' in request.admin_note:
                amount = 25000.0
        await meta_capi_service.send_purchase_event(user, amount_ngn=amount, tier_name=request.admin_note)
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
    if not await check_channel_membership(getattr(context, 'bot', None), query.from_user.id):
        await query.answer('Channel membership required.', show_alert=True)
        await query.message.reply_text(
            LOCKED_TERMINAL_TEXT,
            reply_markup=_channel_locked_keyboard(),
        )
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


async def channel_gate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    is_member = await check_channel_membership(getattr(context, 'bot', None), query.from_user.id)
    if not is_member:
        await query.answer(
            '❌ You have not joined the channel yet. Please tap "Join Official Channel" above, join, then tap verify!',
            show_alert=True,
        )
        return
    await query.answer('✅ Channel membership verified!')
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(query.from_user)
        if user.funnel_step in ('1_STARTED', None):
            service.set_funnel_step(user, '2_CHANNEL_JOINED')
            await meta_capi_service.send_lead_event(user)
        if user.status == UserStatus.APPROVED:
            await query.edit_message_text(
                '⚡ BCGAME AI SIGNALS — VIP ACCESS\n\n'
                f'👋 Welcome back {query.from_user.first_name or "Trader"}!\n'
                '✅ Access active! Choose what you want to do below.',
                reply_markup=_approved_menu(),
            )
            return
        await query.edit_message_text('🔓 Terminal Unlocked! Channel membership confirmed.')
        await send_onboarding_welcome(context.bot, query.from_user.id, query.from_user, db)


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member or not chat_member.new_chat_member:
        return
    if settings.telegram_channel_id:
        expected = str(settings.telegram_channel_id)
        current_id = str(chat_member.chat.id)
        current_username = f"@{chat_member.chat.username}" if chat_member.chat.username else ""
        if current_id != expected and current_username.lower() != expected.lower():
            return
    old_status = chat_member.old_chat_member.status if chat_member.old_chat_member else None
    new_status = chat_member.new_chat_member.status
    was_member = old_status in ('member', 'administrator', 'creator')
    is_member = new_status in ('member', 'administrator', 'creator')
    if not was_member and is_member:
        tg_user = chat_member.new_chat_member.user
        if not tg_user or tg_user.is_bot:
            return
        with SessionLocal() as db:
            service = OnboardingService(db)
            user = service.get_or_create_user(tg_user)
            if user.funnel_step in ('1_STARTED', None):
                service.set_funnel_step(user, '2_CHANNEL_JOINED')
                await meta_capi_service.send_lead_event(user)
            if user.status != UserStatus.APPROVED and not user.is_blocked:
                try:
                    await send_onboarding_welcome(context.bot, tg_user.id, tg_user, db)
                except Exception:
                    pass


async def session_discipline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    from datetime import datetime, timedelta, timezone
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.telegram_user_id == query.from_user.id))
        if not user:
            await query.answer('User record not found.', show_alert=True)
            return
        user.consecutive_wins = (user.consecutive_wins or 0) + 1
        now = datetime.now(timezone.utc)
        threshold = settings.session_discipline_win_threshold
        if user.consecutive_wins >= threshold:
            cooldown_mins = settings.session_discipline_cooldown_minutes
            user.consecutive_wins = 0
            if cooldown_mins > 0:
                user.session_cooldown_until = now + timedelta(minutes=cooldown_mins)
                db.commit()
                await query.answer('🏆 3-WIN TARGET HIT! Locking in profits! 🔥', show_alert=True)
                await query.message.reply_text(
                    '🏆 3 CONSECUTIVE WINS ACHIEVED! 🔥🔥🔥\n\n'
                    'Outstanding trading session! You hit the 3-Win Target.\n\n'
                    f'AI Discipline Protection enforces a {cooldown_mins}-minute cooldown to lock in 100% of your profits '
                    'and protect your capital from over-trading.\n\n'
                    'Take a well-deserved break and return when the session reopens to keep your win streak sharp!'
                )
            else:
                user.session_cooldown_until = None
                db.commit()
                await query.answer('🏆 3 CONSECUTIVE WINS ACHIEVED! 🔥🔥🔥', show_alert=True)
                await query.message.reply_text(
                    '🏆 3 CONSECUTIVE WINS ACHIEVED! 🔥🔥🔥\n\n'
                    'Outstanding trading session! You hit 3 wins in a row.\n\n'
                    'Your terminal remains 100% unlocked — tap ⚡ Scan Market anytime for your next round!'
                )
        else:
            db.commit()
            await query.answer(f'✅ Win recorded! Session streak: {user.consecutive_wins}/{threshold} wins 🔥', show_alert=True)

