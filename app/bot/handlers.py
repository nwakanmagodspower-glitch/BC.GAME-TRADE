from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from app.bot.signal_views import build_scan_prompt_keyboard, build_signal_keyboard, format_scan_context, format_signal
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
        [InlineKeyboardButton('⚡ Signal', callback_data='menu:signal'), InlineKeyboardButton('📈 Results', callback_data='menu:results')],
        [InlineKeyboardButton('ℹ️ How It Works', callback_data='menu:help'), InlineKeyboardButton('🆘 Support', callback_data='menu:support')],
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
            await update.effective_chat.send_message('⚡ BC.GAME BTC 5s Signals\n\nYour access is active. Choose an option.', reply_markup=_approved_menu())
            return
        if user.status == UserStatus.SUSPENDED:
            await update.effective_chat.send_message('Your access is suspended. Please contact support.')
            return
        if user.status == UserStatus.REJECTED:
            await update.effective_chat.send_message('Your verification was not approved. Please contact support if needed.')
            return
        step = user.onboarding_step
        if step == OnboardingStep.START:
            service.set_step(user, OnboardingStep.REGISTRATION); step = OnboardingStep.REGISTRATION
        if step == OnboardingStep.REGISTRATION:
            keyboard = []
            if settings.bcgame_registration_url:
                keyboard.append([InlineKeyboardButton('🔗 Create BC.GAME Account', url=settings.bcgame_registration_url)])
            keyboard.append([InlineKeyboardButton('✅ Continue', callback_data='onboard:registered')])
            await update.effective_chat.send_message('⚡ BC.GAME BTC 5s Signals\n\nGet real-time BTC/USD 5-second Up/Down market analysis and trade signals.\n\n🔐 Private Access\nComplete the quick verification process to unlock the signal dashboard.\n\n1️⃣ Create Your Account\nRegister on BC.GAME using the button below. When you are done, return here and tap Continue.', reply_markup=InlineKeyboardMarkup(keyboard)); return
        if step == OnboardingStep.DEPOSIT:
            await _send_deposit_step(update); return
        if step == OnboardingStep.BC_ID:
            await update.effective_chat.send_message('3️⃣ Enter Your BC.GAME User ID\n\nSend your BC.GAME User ID here as a message.'); return
        if step == OnboardingStep.PROFILE_PROOF:
            await update.effective_chat.send_message('4️⃣ Confirm Your Account\n\nSend a clear screenshot of your BC.GAME profile showing your User ID.'); return
        if step == OnboardingStep.DEPOSIT_PROOF:
            request = service.current_request(user); proof_count = len(request.deposit_proof_file_ids or [])
            if proof_count:
                await update.effective_chat.send_message(f'5️⃣ Confirm Your Deposit\n\n{proof_count} deposit screenshot(s) received. Add another if needed, or submit your verification.', reply_markup=_button('✅ Submit Verification', 'onboard:submit'))
            else:
                await update.effective_chat.send_message('5️⃣ Confirm Your Deposit\n\nSend at least one clear screenshot showing your BC.GAME deposit.\n\nThe Submit Verification button will appear after your screenshot is received.')
            return
        if step == OnboardingStep.REVIEW:
            await update.effective_chat.send_message('⏳ Verification submitted successfully.\n\nYour account is now waiting for review. You will be notified here when a decision is made.'); return
        if step == OnboardingStep.RESUBMIT:
            await update.effective_chat.send_message('🔄 New verification requested.\n\nSend your BC.GAME User ID to begin again.')


async def _send_deposit_step(update: Update):
    keyboard = []
    if settings.bcgame_deposit_url: keyboard.append([InlineKeyboardButton('💳 Open Deposit Page', url=settings.bcgame_deposit_url)])
    keyboard.append([InlineKeyboardButton('✅ Continue After Deposit', callback_data='onboard:deposited')])
    await update.effective_chat.send_message('2️⃣ Make Your Deposit\n\nOpen the BC.GAME deposit page and complete your deposit. Then return here and tap Continue After Deposit.', reply_markup=InlineKeyboardMarkup(keyboard))


async def onboarding_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user: return
    with SessionLocal() as db:
        service = OnboardingService(db); user = service.get_or_create_user(query.from_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED):
            await query.answer('This onboarding action is not available.', show_alert=True); return
        if query.data == 'onboard:registered' and user.onboarding_step == OnboardingStep.REGISTRATION:
            await query.answer(); service.set_step(user, OnboardingStep.DEPOSIT); await query.edit_message_text('Account step completed ✅'); await _send_deposit_step(update); return
        if query.data == 'onboard:deposited' and user.onboarding_step == OnboardingStep.DEPOSIT:
            await query.answer(); service.set_step(user, OnboardingStep.BC_ID); await query.edit_message_text('Deposit step completed ✅\n\n3️⃣ Enter Your BC.GAME User ID\n\nSend your BC.GAME User ID here as a message.'); return
        if query.data == 'onboard:submit' and user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try: service.submit(user)
            except ValueError as exc:
                message = str(exc)
                if message == 'Verification packet is incomplete': message = 'Please send at least one deposit screenshot before submitting.'
                await query.answer(message, show_alert=True); return
            await query.answer('Verification submitted ✅'); await query.edit_message_text('✅ Verification Submitted\n\nYour details have been sent for review.\n\nYou will receive a message here as soon as your access is approved.'); return
        await query.answer('That step is no longer active.', show_alert=True)


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user: return
    with SessionLocal() as db:
        service = OnboardingService(db); user = service.get_or_create_user(update.effective_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED): return
        if user.onboarding_step == OnboardingStep.BC_ID:
            value = update.message.text.strip()
            if len(value) < 2 or len(value) > 255: await update.message.reply_text('Please send a valid BC.GAME User ID.'); return
            service.set_bcgame_user_id(user, value); await update.message.reply_text('User ID received ✅\n\n4️⃣ Confirm Your Account\n\nNow send a clear screenshot of your BC.GAME profile showing that User ID.')


async def photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.photo or not update.effective_user: return
    photo = update.message.photo[-1]; file_id = photo.file_id
    if photo.file_size is not None and photo.file_size > settings.verification_max_photo_bytes: await update.message.reply_text('That screenshot is too large. Please send a smaller image.'); return
    with SessionLocal() as db:
        service = OnboardingService(db); user = service.get_or_create_user(update.effective_user)
        if _is_access_blocked(user) or user.status in (UserStatus.APPROVED, UserStatus.REJECTED): return
        if user.onboarding_step == OnboardingStep.PROFILE_PROOF:
            service.set_profile_proof(user, file_id); await update.message.reply_text('Profile screenshot received ✅\n\n5️⃣ Confirm Your Deposit\n\nNow send at least one clear screenshot showing your BC.GAME deposit.\n\nThe Submit Verification button will appear after the deposit screenshot is received.'); return
        if user.onboarding_step == OnboardingStep.DEPOSIT_PROOF:
            try: request = service.add_deposit_proof(user, file_id)
            except ValueError as exc: await update.message.reply_text(str(exc)); return
            count = len(request.deposit_proof_file_ids or []); await update.message.reply_text(f'Deposit screenshot received ✅ ({count})\n\nYou can send another screenshot if needed, or submit your verification now.', reply_markup=_button('✅ Submit Verification', 'onboard:submit'))


async def admin_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data: return
    if not settings.owner_telegram_id or query.from_user.id != settings.owner_telegram_id or not update.effective_chat or update.effective_chat.type != 'private' or update.effective_chat.id != settings.owner_telegram_id:
        await query.answer('Owner review is available only in the owner private chat.', show_alert=True); return
    try: _, action, request_id_text = query.data.split(':', 2); request_id = int(request_id_text)
    except (ValueError, AttributeError): await query.answer('Invalid admin action.', show_alert=True); return
    with SessionLocal() as db:
        service = OnboardingService(db)
        try: request, user, changed = service.review(request_id, query.from_user.id, action)
        except ValueError as exc: await query.answer(str(exc), show_alert=True); return
    if not changed: await query.answer('Already saved.', show_alert=True); return
    await query.answer('Saved'); await query.edit_message_reply_markup(reply_markup=None)
    if action == 'approve':
        await context.bot.send_message(user.telegram_user_id, 'Verification approved ✅\n\nYour BTC 5s signal access is active.', reply_markup=_approved_menu()); await query.message.reply_text(f'Approved request #{request.id}.')
    elif action == 'resubmit':
        await context.bot.send_message(user.telegram_user_id, 'Your verification needs new evidence. Send your BC.GAME User ID to begin the new packet.'); await query.message.reply_text(f'Resubmission requested for #{request.id}.')
    else:
        await context.bot.send_message(user.telegram_user_id, 'Verification was not approved. Please contact support if needed.'); await query.message.reply_text(f'Rejected request #{request.id}.')


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user or not query.data: return
    with SessionLocal() as db:
        onboarding = OnboardingService(db); user = onboarding.get_or_create_user(query.from_user)
        if user.status != UserStatus.APPROVED or user.is_blocked: await query.answer('Approved access is required.', show_alert=True); return
        if query.data == 'menu:home': await query.answer(); await query.message.reply_text('Choose an option:', reply_markup=_approved_menu()); return
        if query.data == 'menu:signal': await query.answer(); await query.message.reply_text(format_scan_context(), reply_markup=build_scan_prompt_keyboard()); return
        if query.data == 'menu:scan_now':
            await query.answer('Checking the next BC.GAME round…'); result = await UserSignalService(db).request_scan(user.id)
            if not result.available: await query.message.reply_text(result.reason, reply_markup=build_scan_prompt_keyboard()); return
            signal = result.signal; await query.message.reply_text(format_signal(signal), reply_markup=build_signal_keyboard(signal.direction)); return
        if query.data == 'menu:results':
            await query.answer(); recent = db.query(Signal).filter(Signal.requested_by_user_id == user.id).order_by(Signal.id.desc()).limit(10).all()
            if not recent: await query.message.reply_text('You do not have any recent signal results yet.', reply_markup=_approved_menu()); return
            lines = ['📈 MY RECENT 5s SIGNALS', 'Latest 10 • records expire after 10 days', '']
            for signal in recent: lines.append(f'#{signal.id}  {signal.direction.value} — {_result_label(signal)}')
            await query.message.reply_text('\n'.join(lines), reply_markup=_approved_menu()); return
        if query.data == 'menu:help':
            await query.answer(); await query.message.reply_text('ℹ️ HOW IT WORKS\n\n⚡ BC.GAME BTC/USD — 5s Up/Down\n\n1️⃣ Prepare your trade\nOpen BC.GAME Up/Down, select BTC/USD and 5 seconds, then enter your stake before requesting a signal.\n\n2️⃣ Wait for a fresh round\nWhen the new order countdown starts, watch the BC.GAME timer.\n\n3️⃣ Scan at 15–12 seconds\nWhen BC.GAME shows 15, 14, 13, or 12 seconds, return here and tap the matching countdown button immediately.\n\n4️⃣ Read the result\n🟢 UP = upward pressure detected\n🔴 DOWN = downward pressure detected\n⚪ NO TRADE = conditions are not strong enough\n⚠️ UNAVAILABLE = timing or market data is not safe enough for a valid signal\n\n5️⃣ Place the trade manually\nIf you receive UP or DOWN with enough time remaining, return to BC.GAME and tap the same direction before the countdown reaches 0.\n\n6️⃣ Settlement\nAt 0, BC.GAME records the Start Rate. Five seconds later it records the End Rate. If End Rate is above Start Rate, UP wins; otherwise DOWN wins according to the game rules.\n\nSignals are market analysis, not guaranteed outcomes. The bot never places a wager for you.', reply_markup=_approved_menu()); return
        if query.data == 'menu:support':
            await query.answer()
            if settings.support_url: await query.message.reply_text('Need help?', reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🆘 Open Support', url=settings.support_url)]]))
            else: await query.message.reply_text('Support contact has not been configured yet.', reply_markup=_approved_menu())
            return
    await query.answer()
