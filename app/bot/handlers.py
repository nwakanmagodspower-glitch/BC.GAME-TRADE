from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.entities import OnboardingStep, UserStatus
from app.services.onboarding import OnboardingService

settings = get_settings()


def _button(label: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)]])


def _approved_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📊 BTC Signal', callback_data='menu:signal')],
        [InlineKeyboardButton('📈 My Results', callback_data='menu:results')],
        [InlineKeyboardButton('ℹ️ How It Works', callback_data='menu:help')],
        [InlineKeyboardButton('🆘 Support', callback_data='menu:support')],
    ])


def _is_access_blocked(user) -> bool:
    return bool(user.is_blocked or user.status == UserStatus.SUSPENDED)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    if not tg_user or not update.effective_chat:
        return

    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(tg_user)

        if user.is_blocked:
            await update.effective_chat.send_message('Your bot access is currently blocked. Please contact support.')
            return

        if user.status == UserStatus.APPROVED:
            await update.effective_chat.send_message(
                'Welcome back. Your access is active. Choose an option below.',
                reply_markup=_approved_menu(),
            )
            return

        if user.status == UserStatus.SUSPENDED:
            await update.effective_chat.send_message('Your access is currently suspended. Please contact support.')
            return

        if user.status == UserStatus.REJECTED:
            await update.effective_chat.send_message('Your verification was not approved. Please contact support if you believe this is an error.')
            return

        step = user.onboarding_step
        if step == OnboardingStep.START:
            service.set_step(user, OnboardingStep.REGISTRATION)
            step = OnboardingStep.REGISTRATION

        if step == OnboardingStep.REGISTRATION:
            text = 'Step 1 of 5 — Registration\n\nCreate your BC.GAME account using the registration link below. When finished, return here and continue.'
            keyboard = []
            if settings.bcgame_registration_url:
                keyboard.append([InlineKeyboardButton('Open BC.GAME Registration', url=settings.bcgame_registration_url)])
            keyboard.append([InlineKeyboardButton('I Have Registered', callback_data='onboard:registered')])
            await update.effective_chat.send_message(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        if step == OnboardingStep.DEPOSIT:
            await _send_deposit_step(update)
            return

        if step == OnboardingStep.BC_ID:
            await update.effective_chat.send_message('Step 3 of 5 — BC.GAME User ID\n\nSend your BC.GAME User ID as a text message.')
            return

        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('Step 4 of 5 — Profile Proof\n\nSend a clear screenshot of your BC.GAME profile showing the User ID.')
            return

        if step == OnboardingStep.DEPOSIT_PROOF:
            await update.effective_chat.send_message(
                'Step 5 of 5 — Deposit Proof\n\nSend one or more clear screenshots showing your deposit. When all screenshots have been sent, tap Finish Verification.',
                reply_markup=_button('Finish Verification', 'onboard:submit'),
            )
            return

        if step == OnboardingStep.REVIEW:
            await update.effective_chat.send_message('Your verification has been submitted and is waiting for admin review.')
            return

        if step == OnboardingStep.RESUBMIT:
            await update.effective_chat.send_message('Your verification needs to be submitted again. Send your BC.GAME User ID to begin the new verification packet.')


async def _send_deposit_step(update: Update):
    keyboard = []
    if settings.bcgame_deposit_url:
        keyboard.append([InlineKeyboardButton('Open Deposit Page', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('I Have Deposited', callback_data='onboard:deposited')])
    await update.effective_chat.send_message(
        'Step 2 of 5 — Deposit\n\nMake your deposit on BC.GAME. When the deposit is complete, return here and continue.',
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
            await query.answer('This onboarding action is not available for your account.', show_alert=True)
            return

        if query.data == 'onboard:registered' and user.onboarding_step == OnboardingStep.REGISTRATION:
            service.set_step(user, OnboardingStep.DEPOSIT)
            await query.edit_message_text('Registration step saved ✅')
            await _send_deposit_step(update)
            return

        if query.data == 'onboard:deposited' and user.onboarding_step == OnboardingStep.DEPOSIT:
            service.set_step(user, OnboardingStep.BC_ID)
            await query.edit_message_text('Deposit step saved ✅\n\nStep 3 of 5 — Send your BC.GAME User ID as a text message.')
            return

        if query.data == 'onboard:submit' and user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try:
                request = service.submit(user)
            except ValueError as exc:
                await query.answer(str(exc), show_alert=True)
                return
            await query.edit_message_text('Verification submitted ✅\n\nYour access is now waiting for manual admin review.')
            await _send_admin_packet(context, user, request)
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
            await update.message.reply_text('User ID saved ✅\n\nNow send a clear screenshot of your BC.GAME profile showing this User ID.')


async def photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo or not update.effective_user:
        return
    file_id = update.message.photo[-1].file_id
    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(update.effective_user)

        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            return

        if user.onboarding_step == OnboardingStep.PROFILE_PROOF:
            service.set_profile_proof(user, file_id)
            await update.message.reply_text(
                'Profile screenshot saved ✅\n\nNow send your deposit screenshot(s). You can send more than one. When finished, tap the button below.',
                reply_markup=_button('Finish Verification', 'onboard:submit'),
            )
            return

        if user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            request = service.add_deposit_proof(user, file_id)
            count = len(request.deposit_proof_file_ids or [])
            await update.message.reply_text(
                f'Deposit screenshot saved ✅ ({count})\n\nSend another if needed, or finish verification.',
                reply_markup=_button('Finish Verification', 'onboard:submit'),
            )


async def _send_admin_packet(context: ContextTypes.DEFAULT_TYPE, user, request):
    admin_chat = settings.admin_chat_id or settings.owner_telegram_id
    if not admin_chat:
        return

    username = f'@{user.telegram_username}' if user.telegram_username else 'None'
    text = (
        '🔐 NEW VERIFICATION REQUEST\n\n'
        f'Request ID: {request.id}\n'
        f'Name: {user.first_name or "Unknown"}\n'
        f'Username: {username}\n'
        f'Telegram ID: {user.telegram_user_id}\n'
        f'BC.GAME User ID: {request.bcgame_user_id}\n\n'
        'Check this ID in the affiliate dashboard and verify the profile/deposit proof before approving.'
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ Approve', callback_data=f'admin:approve:{request.id}')],
        [InlineKeyboardButton('🔄 Resubmit', callback_data=f'admin:resubmit:{request.id}')],
        [InlineKeyboardButton('❌ Reject', callback_data=f'admin:reject:{request.id}')],
    ])
    await context.bot.send_message(admin_chat, text, reply_markup=keyboard)
    await context.bot.send_photo(admin_chat, request.profile_proof_file_id, caption='BC.GAME profile proof')
    for index, file_id in enumerate(request.deposit_proof_file_ids or [], start=1):
        await context.bot.send_photo(admin_chat, file_id, caption=f'Deposit proof {index}')


async def admin_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return
    admin_ids = {value for value in (settings.owner_telegram_id, settings.admin_chat_id) if value is not None}
    if query.from_user.id not in admin_ids:
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
        await context.bot.send_message(
            user.telegram_user_id,
            'Verification approved ✅\n\nYour access is now active.',
            reply_markup=_approved_menu(),
        )
        await query.message.reply_text(f'Approved request #{request.id}.')
    elif action == 'resubmit':
        await context.bot.send_message(
            user.telegram_user_id,
            'Your verification needs to be submitted again.\n\nPlease send your BC.GAME User ID to begin again.',
        )
        await query.message.reply_text(f'Resubmission requested for #{request.id}.')
    else:
        await context.bot.send_message(user.telegram_user_id, 'Verification was not approved. Please contact support if you believe this is an error.')
        await query.message.reply_text(f'Rejected request #{request.id}.')


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data:
        return

    with SessionLocal() as db:
        service = OnboardingService(db)
        user = service.get_or_create_user(query.from_user)
        if user.status != UserStatus.APPROVED or user.is_blocked:
            await query.answer('Your approved access is required.', show_alert=True)
            return

    await query.answer()
    if query.data == 'menu:signal':
        await query.message.reply_text('BTC Signal is not active yet. Market intelligence is being prepared.')
    elif query.data == 'menu:results':
        await query.message.reply_text('Results will appear here after the signal engine is connected.')
    elif query.data == 'menu:help':
        await query.message.reply_text('This bot will provide on-demand BTC/USDT Up/Down analysis. Signals remain disabled until market intelligence is validated.')
    elif query.data == 'menu:support':
        if settings.support_url:
            await query.message.reply_text(f'Support: {settings.support_url}')
        else:
            await query.message.reply_text('Support contact has not been configured yet.')
