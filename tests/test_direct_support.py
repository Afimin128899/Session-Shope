"""Direct support has no purchase requirement, ticket mutations or payment hooks."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from aiogram.types import Message, CallbackQuery, User, Chat
from test_payments import db
from database import tickets
from handlers import direct_support as support
from handlers import quality as quality_ui
from utils.support_access import is_support_event
from utils.maintenance import MaintenanceMiddleware
from middlewares.subscription_middleware import SubscriptionMiddleware


def message(user_id=42, **values):
    return NS(from_user=NS(id=user_id, full_name='<Покупатель>', username='buyer'),
              chat=NS(id=user_id, type='private'), message_id=12, text='Вопрос', content_type='text',
              answer=AsyncMock(), bot=NS(send_message=AsyncMock(), copy_message=AsyncMock()), **values)


class DirectSupportTests(unittest.IsolatedAsyncioTestCase):
    async def test_router_delivers_private_support_messages_and_ignores_groups(self):
        from aiogram.dispatcher.event.bases import UNHANDLED
        msg=message()
        state=NS(get_data=AsyncMock(return_value={}))
        with patch.object(support,'relay',AsyncMock()) as relay:
            await support.support_router.propagate_event(update_type='message',event=msg,bot=msg.bot,state=state,raw_state='DirectSupport:message')
            relay.assert_awaited_once_with(msg,order=None,warranty=False)
            relay.reset_mock();msg.chat.type='group'
            result=await support.support_router.propagate_event(update_type='message',event=msg,bot=msg.bot,state=state,raw_state='DirectSupport:message')
            self.assertIs(result,UNHANDLED);relay.assert_not_awaited()

    async def test_any_user_can_start_without_purchase_or_ticket(self):
        call=NS(from_user=NS(id=42),answer=AsyncMock())
        state=NS(clear=AsyncMock(),update_data=AsyncMock(),set_state=AsyncMock())
        with patch.object(support,'edit_message_safe',AsyncMock()) as screen, patch.object(db,'get_purchase_for_user',AsyncMock()) as purchase, patch.object(tickets,'create_general',AsyncMock()) as ticket:
            await support.support(call,state)
            purchase.assert_not_awaited();ticket.assert_not_awaited()
            state.set_state.assert_awaited_once_with(support.DirectSupport.message)
            self.assertEqual(screen.call_args.kwargs['section'],'support')

    async def test_text_and_media_are_copied_to_admins_with_reply_target(self):
        for kind in ['text','photo','document','voice','video']:
            msg=message();msg.content_type=kind
            with patch.object(support,'ADMIN_IDS',[99,99,100]),patch.object(tickets,'create_general',AsyncMock()) as ticket:
                self.assertTrue(await support.relay(msg))
                self.assertEqual(msg.bot.copy_message.await_count,2)
                msg.bot.copy_message.assert_any_await(chat_id=99,from_chat_id=42,message_id=12)
                header=msg.bot.send_message.call_args_list[0]
                self.assertIn('&lt;Покупатель&gt;',header.args[1])
                self.assertEqual(header.kwargs['reply_markup'].inline_keyboard[0][0].callback_data,'support_reply:42')
                ticket.assert_not_awaited()

    async def test_no_false_acknowledgment_if_admins_cannot_receive_body(self):
        msg=message();msg.bot.copy_message.side_effect=RuntimeError('blocked')
        with patch.object(support,'ADMIN_IDS',[99]):
            self.assertFalse(await support.relay(msg))
        self.assertIn('не удалось',msg.answer.call_args.args[0])

    async def test_empty_admin_list_reports_failure(self):
        msg=message()
        with patch.object(support,'ADMIN_IDS',[]): self.assertFalse(await support.relay(msg))
        msg.bot.send_message.assert_not_awaited()

    async def test_reply_button_is_admin_only_and_preserves_original_message(self):
        call=NS(from_user=NS(id=42),data='support_reply:77',answer=AsyncMock(),message=NS(answer=AsyncMock(),edit_text=AsyncMock()))
        state=NS(clear=AsyncMock(),update_data=AsyncMock(),set_state=AsyncMock())
        with patch.object(support,'ADMIN_IDS',[99]):
            await support.begin_reply(call,state)
            state.set_state.assert_not_awaited()
            call.from_user.id=99
            await support.begin_reply(call,state)
        state.update_data.assert_awaited_once_with(support_recipient=77)
        call.message.edit_text.assert_not_awaited();call.message.answer.assert_awaited_once()

    async def test_admin_reply_uses_state_recipient_and_rechecks_role(self):
        msg=message(99);state=NS(get_data=AsyncMock(return_value={'support_recipient':42}),clear=AsyncMock())
        with patch.object(support,'ADMIN_IDS',[99]): await support.admin_message(msg,state)
        msg.bot.copy_message.assert_awaited_once_with(chat_id=42,from_chat_id=99,message_id=12)
        msg.bot.copy_message.reset_mock()
        with patch.object(support,'ADMIN_IDS',[]): await support.admin_message(msg,state)
        msg.bot.copy_message.assert_not_awaited();state.clear.assert_awaited_once()

    async def test_purchase_context_requires_ownership_but_general_help_does_not(self):
        call=NS(from_user=NS(id=42),data='purchase_help:7',answer=AsyncMock())
        with patch.object(db,'get_purchase_for_user',AsyncMock(return_value=None)) as get,patch.object(support,'begin',AsyncMock()) as begin:
            await support.purchase_help(call,NS())
            get.assert_awaited_once_with(7,42);begin.assert_not_awaited()

    async def test_warranty_rechecked_before_relay_without_creating_ticket(self):
        msg=message()
        with patch.object(db,'get_purchase_for_user',AsyncMock(return_value=None)),patch.object(tickets,'create_ticket',AsyncMock()) as ticket:
            self.assertFalse(await support.relay(msg,order=7,warranty=True))
            ticket.assert_not_awaited();msg.bot.send_message.assert_not_awaited()
        call=NS(data='quality_warranty:7',from_user=NS(id=42),answer=AsyncMock())
        with patch.object(db,'get_purchase_for_user',AsyncMock(return_value={'id':7})),patch.object(support.quality,'warranty',return_value={'active':True}),patch.object(quality_ui,'begin_direct_support',AsyncMock()) as begin:
            await quality_ui.begin_warranty(call,NS())
            begin.assert_awaited_once_with(call,unittest.mock.ANY,order=7,warranty=True)

    async def test_old_buttons_do_not_reopen_archived_tickets(self):
        with patch.object(support,'begin',AsyncMock()) as begin,patch.object(tickets,'reply',AsyncMock()) as reply:
            call=NS(data='tk_reply:9');state=NS()
            await support.legacy_support(call,state)
            begin.assert_awaited_once_with(call,state);reply.assert_not_awaited()

    async def test_successful_payments_and_commands_are_never_support_messages(self):
        for kind in ['successful_payment','refunded_payment','new_chat_members']:
            msg=message();msg.content_type=kind
            self.assertFalse(support.copyable(msg))
        msg=message();msg.text='/start';self.assertFalse(support.copyable(msg))

    async def test_help_bypasses_subscription_and_maintenance_but_shop_does_not(self):
        user=User(id=42,is_bot=False,first_name='Buyer')
        msg=Message(message_id=1,date=datetime.now(timezone.utc),chat=Chat(id=42,type='private'),from_user=user,text='/support')
        state=NS(get_state=AsyncMock(return_value=None))
        callback=CallbackQuery(id='test',from_user=user,chat_instance='chat',message=msg,data='support')
        for event in [msg,callback]:
            for middleware in [MaintenanceMiddleware(),SubscriptionMiddleware()]:
                handler=AsyncMock()
                await middleware(handler,event,{'state':state,'bot':NS()})
                handler.assert_awaited_once()
        shop=callback.model_copy(update={'data':'buy'})
        self.assertFalse(await is_support_event(shop,{'state':state}))
        self.assertFalse(await is_support_event(msg.model_copy(update={'text':'/start'}),{'state':state}))
        state.get_state.return_value='DirectSupport:message'
        self.assertTrue(await is_support_event(msg.model_copy(update={'text':'Помогите'}),{'state':state}))
