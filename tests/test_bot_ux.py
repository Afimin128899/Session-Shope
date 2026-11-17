import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from test_payments import db
from handlers.user import balance

class FundingUXTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_limit_is_displayed(self):
        call=NS(answer=AsyncMock())
        state=NS(clear=AsyncMock(),set_state=AsyncMock(),update_data=AsyncMock())
        with patch.object(balance.payments,'get_methods',AsyncMock(return_value=[{'id':'heleket','enabled':True,'name':'Crypto','min':50,'max':7500}])),patch.object(balance,'edit_message_safe',AsyncMock()) as edit:
            await balance._start_deposit(call,state,'heleket')
        self.assertIn('7 500',edit.call_args.args[1])
        self.assertNotIn('1 000 000',edit.call_args.args[1])

    async def test_unavailable_payments_offer_support(self):
        call=NS(answer=AsyncMock());state=NS(clear=AsyncMock())
        with patch.object(balance.payments,'get_methods',AsyncMock(return_value=[])),patch.object(balance,'edit_message_safe',AsyncMock()) as edit:
            await balance.topup_balance_menu(call,state)
        callbacks=[b.callback_data for row in edit.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(callbacks,['support','balance'])
