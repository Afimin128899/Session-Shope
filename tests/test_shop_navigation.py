"""Screenshot navigation, truthful stock and single-debit bulk confirmation."""
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from test_payments import db
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from handlers.user import shop, shop_navigation as ui
from database import shop_navigation as store, commerce
from keyboards import user_kb
from utils import button_icons


def flatten(markup):
    return [b for row in markup.inline_keyboard for b in row]


class ShoppingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage=MemoryStorage()
        self.state=FSMContext(self.storage,StorageKey(bot_id=1,chat_id=42,user_id=42))
        self.call=NS(data='buy',from_user=NS(id=42),message=NS(answer=AsyncMock()),answer=AsyncMock())
        self.edit=AsyncMock();p=patch.object(ui,'edit_message_safe',self.edit);p.start();self.addCleanup(p.stop)

    async def asyncTearDown(self):
        await self.storage.close()

    async def test_entry_matches_type_rows_and_back(self):
        await shop.open_shop(self.call,self.state)
        markup=self.edit.call_args.kwargs['reply_markup']
        self.assertEqual([[b.text for b in row] for row in markup.inline_keyboard],[['Авторег','С отлегой'],['Премиум'],['Назад']])
        self.assertEqual([b.style for b in flatten(markup)[:3]],['success']*3)
        self.assertIn('Выберите вид аккаунта',self.edit.call_args.args[1])

    async def test_new_buttons_use_only_requested_pack_and_no_standard_emoji(self):
        icons={'country':'100001','catalog':'100002','calendar':'100003','premium':'100004','money':'100005','back':'100006'}
        with patch.dict(button_icons.PACK_ICONS,icons,clear=True):
            await ui.entry(self.call,self.state)
            markup=button_icons.decorate(self.edit.call_args.kwargs['reply_markup'])
            self.assertTrue(all(b.icon_custom_emoji_id in icons.values() for b in flatten(markup)))
            sample=ui.btn('🇺🇸 США · от 99 ₽','sn:country:auto:us')
            self.assertEqual(sample.text,'США · от 99 ₽')
            self.assertEqual(sample.icon_custom_emoji_id,'100001')
        # Offline pack loading must not introduce a different pack or plain emoji.
        with patch.dict(button_icons.PACK_ICONS,{},clear=True):
            await ui.entry(self.call,self.state)
            markup=button_icons.decorate(self.edit.call_args.kwargs['reply_markup'])
            self.assertTrue(all(b.icon_custom_emoji_id is None for b in flatten(markup)))

    async def test_registered_callback_router_reaches_country_menu(self):
        self.call.data='sn:home:auto'
        self.call.message.chat=NS(type='private')
        with patch.object(ui,'show_countries',AsyncMock()) as show:
            await ui.router.propagate_event(update_type='callback_query',event=self.call,state=self.state,bot=NS())
            show.assert_awaited_once_with(self.call,self.state,'auto')

    async def test_main_menu_keeps_funding_and_omits_excluded_buttons_and_apps(self):
        with patch.object(user_kb,'get_button_label',AsyncMock(return_value=None)),patch.object(user_kb,'get_setting',AsyncMock(return_value='')):
            menu=await user_kb.main_menu(42)
        buttons=flatten(menu);callbacks={b.callback_data for b in buttons}
        self.assertEqual(callbacks,{'buy','topup_balance','my_profile','support','all_categories:0'})
        self.assertTrue(all(b.web_app is None for b in buttons))
        self.assertNotIn('Номер для смены',' '.join(b.text for b in buttons))
        self.assertNotIn('Бот рассылки',' '.join(b.text for b in buttons))
        self.assertEqual(menu.inline_keyboard[1][0].style,'success')

    async def test_home_has_real_cheapest_price_country_count_and_two_column_tiles(self):
        items=[{'nation':'us','name':'США','flag':'🇺🇸','count':2,'min_price':Decimal('71.25')},
               {'nation':'in','name':'Индия','flag':'🇮🇳','count':10,'min_price':Decimal('92')},
               {'nation':'cl','name':'Чили','flag':'🇨🇱','count':1,'min_price':Decimal('105')}]
        with patch.object(store,'countries',AsyncMock(return_value=items)):
            await ui.show_countries(self.call,self.state,'auto')
        rows=self.edit.call_args.kwargs['reply_markup'].inline_keyboard
        self.assertEqual(rows[0][0].text,'Самый дешёвый — 71,25 ₽')
        self.assertEqual([b.callback_data for b in rows[1]],['sn:search:auto'])
        self.assertEqual(rows[2][0].callback_data,'sn:bulk:auto:all:0')
        self.assertEqual(len(rows[4]),2)
        self.assertTrue(any(b.text=='Все страны (3)' for b in flatten(self.edit.call_args.kwargs['reply_markup'])))

    async def test_empty_type_keeps_navigation_without_fake_price(self):
        with patch.object(store,'countries',AsyncMock(return_value=[])):
            await ui.show_countries(self.call,self.state,'premium')
        buttons=flatten(self.edit.call_args.kwargs['reply_markup'])
        self.assertIn('0 товаров',buttons[0].text);self.assertNotIn('₽',buttons[0].text)
        self.assertIn('0 товаров',self.edit.call_args.args[1])
        self.assertTrue(any(b.callback_data=='buy' for b in buttons))

    async def test_years_use_three_columns_and_actual_year_prices(self):
        years=[{'year':2014+i,'count':1,'min_price':Decimal(120+i)} for i in range(6)]
        with patch.object(store,'years',AsyncMock(return_value=years)):
            await ui.show_years(self.call,self.state,'aged','us')
        rows=self.edit.call_args.kwargs['reply_markup'].inline_keyboard
        self.assertEqual([len(row) for row in rows],[3,3,1,1])
        self.assertEqual(rows[0][0].callback_data,'sn:products:aged:us:2014:0')
        self.assertIn('120 ₽',rows[0][0].text)

    async def test_permanent_spam_group_is_named_and_preserved_in_navigation(self):
        items=[{'nation':'us~clear','name':'США','count':2,'min_price':Decimal(99)},
               {'nation':'us~permanent','name':'США Вечный СБ','count':1,'min_price':Decimal(10)}]
        with patch.object(store,'countries',AsyncMock(return_value=items)):
            await ui.show_countries(self.call,self.state,'auto')
        buttons=flatten(self.edit.call_args.kwargs['reply_markup'])
        permanent=next(b for b in buttons if b.callback_data=='sn:country:auto:us~permanent')
        self.assertIn('США Вечный СБ',permanent.text)
        self.assertTrue(any(b.text=='Все страны (1)' for b in buttons))
        self.call.data=permanent.callback_data
        with patch.object(ui,'show_products',AsyncMock()) as show:
            await ui.navigate(self.call,self.state)
            show.assert_awaited_once_with(self.call,self.state,'auto','us~permanent')
        with patch.object(store,'years',AsyncMock(return_value=[{'year':2015,'count':1,'min_price':Decimal(10)}])):
            await ui.show_years(self.call,self.state,'aged','us~permanent')
        self.assertIn('США Вечный СБ',self.edit.call_args.args[1])
        self.assertIn('us~permanent',flatten(self.edit.call_args.kwargs['reply_markup'])[0].callback_data)

    async def test_bulk_confirmation_keeps_selected_spam_group(self):
        quote={'items':[{'account_id':7,'price':'10','spam_status':'permanent'}], 'total':'10','rate':'0','created_ids':[7]}
        with patch.object(store,'reserve_bulk',AsyncMock(return_value=quote)) as reserve:
            await ui.quote_bulk(self.call,self.state,'auto','us~permanent',0,1)
            reserve.assert_awaited_once_with(42,'auto','us~permanent',1,0)
        self.assertIn('США Вечный СБ',self.edit.call_args.args[1])

    async def test_generated_product_buttons_reach_shared_confirmation(self):
        items=[{'id':21,'number':'+15551234567','price':Decimal(99)}]
        with patch.object(store,'products',AsyncMock(return_value=(items,1,0))):
            await ui.show_products(self.call,self.state,'aged','us',2014)
        data=flatten(self.edit.call_args.kwargs['reply_markup'])[0].callback_data
        self.call.data=data
        with patch.object(shop,'show_product',AsyncMock()) as show:
            await ui.navigate(self.call,self.state)
            show.assert_awaited_once_with(self.call,self.state,21,back_callback='sn:products:aged:us:2014:0')

    async def test_cheapest_reaches_available_product_and_empty_does_not(self):
        self.call.data='sn:cheap:auto'
        with patch.object(store,'products',AsyncMock(return_value=([{'id':8}],1,0))) as get,patch.object(shop,'show_product',AsyncMock()) as show:
            await ui.navigate(self.call,self.state)
            get.assert_awaited_once_with(42,'auto',quantity=1)
            show.assert_awaited_once_with(self.call,self.state,8,back_callback='sn:home:auto')
        with patch.object(store,'products',AsyncMock(return_value=([],0,0))),patch.object(shop,'show_product',AsyncMock()) as show:
            await ui.navigate(self.call,self.state);show.assert_not_awaited()

    async def test_search_state_and_query_survive_result_pagination(self):
        self.call.data='sn:search:auto';await ui.navigate(self.call,self.state)
        self.assertEqual(await self.state.get_state(),ui.Shopping.search.state)
        with patch.object(store,'countries',AsyncMock(return_value=[])) as get:
            await ui.show_countries(self.call,self.state,'auto',page=0,query='США')
            self.call.data='sn:results:auto:1';await ui.navigate(self.call,self.state)
            get.assert_awaited_with(42,'auto','США')

    async def test_invalid_callbacks_cannot_reserve_or_charge(self):
        with patch.object(store,'reserve_bulk',AsyncMock()) as reserve,patch.object(ui,'checkout_cart',AsyncMock()) as charge:
            for data in ['sn','sn:home:bad','sn:products:aged:xx:2014:0','sn:products:aged:us:evil:0','sn:item:bad:auto:us:0:0','sn:pay:forged']:
                self.call.data=data;await ui.navigate(self.call,self.state)
            reserve.assert_not_awaited();charge.assert_not_awaited()

    async def test_quote_is_kept_server_side_and_not_charged_until_confirmation(self):
        quote={'items':[{'account_id':1,'price':'100','warranty_hours':24,'spam_status':'clear'}],'total':'85','rate':'15','created_ids':[1]}
        with patch.object(store,'reserve_bulk',AsyncMock(return_value=quote)) as reserve,patch.object(ui,'checkout_cart',AsyncMock()) as charge:
            await ui.quote_bulk(self.call,self.state,'auto','us',0,1)
            reserve.assert_awaited_once_with(42,'auto','us',1,0);charge.assert_not_awaited()
        saved=(await self.state.get_data())['bulk_quote']
        self.assertGreater(saved['expires'],time.time())
        data=flatten(self.edit.call_args.kwargs['reply_markup'])[0].callback_data
        self.assertEqual(data,'sn:pay:'+saved['token'])

    async def quote(self,**extra):
        value={'token':'safe','items':[{'account_id':7,'price':'100','warranty_hours':24,'spam_status':'clear'}],
               'total':'100','created_ids':[7],'expires':time.time()+60,**extra}
        await self.state.update_data(bulk_quote=value)
        return value

    async def test_bulk_repeated_confirmation_only_charges_once_and_delivers(self):
        quote=await self.quote()
        with patch.object(ui,'checkout_cart',AsyncMock(return_value={'order_ids':[3],'paid_amount':'100','balance':'900'})) as checkout,patch.object(ui,'get_purchase_for_user',AsyncMock(return_value={'status':'issued','number':'+15551234567','password':'<secret>'})),patch.object(ui,'ADMIN_IDS',[]),patch.object(ui,'after_purchase_menu',AsyncMock(return_value=None)):
            await ui.pay_bulk(self.call,self.state,'safe');await ui.pay_bulk(self.call,self.state,'safe')
            checkout.assert_awaited_once_with(42,quote['items'],expected_total=Decimal('100'))
        self.assertIsNone((await self.state.get_data())['bulk_quote'])
        self.assertIn('&lt;secret&gt;',self.call.message.answer.call_args.args[0])

    async def test_expiry_and_cancel_release_only_created_items_and_never_charge(self):
        for cancel in [False,True]:
            await self.quote(expires=time.time()-1)
            with patch.object(ui,'checkout_cart',AsyncMock()) as checkout,patch.object(commerce,'remove_from_cart',AsyncMock()) as release:
                await ui.pay_bulk(self.call,self.state,'safe',cancel=cancel)
                checkout.assert_not_awaited();release.assert_awaited_once_with(42,7)

    async def test_bulk_price_or_balance_failure_does_not_claim_success(self):
        await self.quote()
        self.call.data='sn:pay:safe'
        with patch.object(ui,'checkout_cart',AsyncMock(side_effect=ui.CheckoutError('Цена изменилась','price_changed'))):
            await ui.navigate(self.call,self.state)
        self.assertIsNotNone((await self.state.get_data())['bulk_quote'])
        self.call.message.answer.assert_not_awaited()
        self.assertIn('Цена изменилась',self.call.answer.call_args.args[0])


class NavigationValidationTests(unittest.TestCase):
    def test_public_filters_reject_unknown_or_injected_values(self):
        for args in [('bad','us',0),('auto','us OR 1=1',0),('aged','us',2012),('auto','us',True)]:
            with self.assertRaises(ValueError): store.validate(*args)
        store.validate('auto','all',0);store.validate('aged','kz',2014)
        store.validate('aged','us~permanent',2015)
        for nation in ['us~bad','all~permanent','us~permanent~clear','xx~permanent']:
            with self.assertRaises(ValueError): store.validate('auto',nation)
