from app.bot.admin_handlers import _admin_menu


def test_admin_menu_offers_disable_when_signals_on():
    markup = _admin_menu(True)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]
    assert 'adminops:signals:off' in callbacks
    assert 'adminops:signals:on' not in callbacks


def test_admin_menu_offers_enable_when_signals_off():
    markup = _admin_menu(False)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]
    assert 'adminops:signals:on' in callbacks
    assert 'adminops:signals:off' not in callbacks
