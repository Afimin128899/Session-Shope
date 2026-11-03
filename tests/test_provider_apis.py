"""Offline provider wire-contract checks; sources: PROVIDER-API-SOURCES.md.

No production credentials, API requests, invoice creation or transfers are used.
"""
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import config
from services import cryptopay, lavepay, xrocket


class ProviderAPITests(unittest.IsolatedAsyncioTestCase):
    def response(self, module, body, status=200, error=None):
        response=NS(status=status,json=AsyncMock(return_value=body))
        request=MagicMock()
        request.__aenter__.return_value=response
        session=NS(request=MagicMock(return_value=request))
        context=MagicMock()
        context.__aenter__.return_value=session
        factory=MagicMock(return_value=context)
        if error: factory.side_effect=error
        patcher=patch.object(module.aiohttp,'ClientSession',factory)
        patcher.start();self.addCleanup(patcher.stop)
        return response,session,factory

    async def test_laveshka_uses_merchant_api_host_key_and_explicit_usd(self):
        invoice={'id':'uuid','status':'pending','pay_url':'https://t.me/laveshka?startapp=fixture'}
        _,session,factory=self.response(lavepay,{'ok':True,'data':invoice})
        with patch.object(lavepay,'LAVE_PAY_API_KEY','fake-test-key'):
            self.assertEqual(await lavepay.create_invoice(12.34,'Description','order-42','owner-payload'),invoice)
        method,url=session.request.call_args.args
        options=session.request.call_args.kwargs
        self.assertEqual((method,url),('POST','https://api.laveshka.io/merchant/v1/invoices'))
        self.assertEqual(options['headers']['X-Api-Key'],'fake-test-key')
        self.assertEqual(options['json'],{'amount':'12.34','currency':'USD','description':'Description','order_id':'order-42','payload':'owner-payload','ttl':3600})
        self.assertFalse(options['allow_redirects'])
        self.assertTrue(factory.call_args.kwargs['trust_env'])

    async def test_xrocket_exchange_mode_preserves_selected_contract(self):
        invoice={'id':'uuid','links':{'telegramBotLink':'https://t.me/fixture'}}
        _,session,_=self.response(xrocket,{'data':invoice})
        with patch.dict(os.environ,{'XROCKET_API_MODE':'exchange'}),patch.object(xrocket,'XROCKET_API_KEY','fake-test-key'):
            self.assertEqual(await xrocket.create_invoice(1.25,'Description','client-order','owner-payload',42,'@fixture'),invoice)
        method,url=session.request.call_args.args
        body=session.request.call_args.kwargs['json']
        self.assertEqual((method,url),('POST','https://pay.api.xrocket.exchange/api/v1/invoices'))
        self.assertEqual(session.request.call_args.kwargs['headers']['Authorization'],'Bearer fake-test-key')
        self.assertEqual(body['priceAmount'],'1.250000')
        self.assertEqual(body['priceCurrency'],'USDT')
        self.assertEqual(body['expiresIn'],3600000)
        self.assertEqual(body['callback'],{'payload':{'orderId':'owner-payload'}})
        self.assertEqual(body['customer'],{'telegramId':'42','telegramUsername':'fixture'})
        self.assertNotIn('Rocket-Pay-Key',session.request.call_args.kwargs['headers'])

    async def test_xrocket_tg_mode_uses_official_sdk_contract_without_fallback(self):
        invoice={'id':12,'link':'https://t.me/xrocket?start=fixture','payload':'owner-payload','status':'active'}
        _,session,_=self.response(xrocket,{'success':True,'data':invoice})
        with patch.dict(os.environ,{'XROCKET_API_MODE':'tg'}),patch.object(xrocket,'XROCKET_API_KEY','fake-test-key'):
            self.assertEqual(await xrocket.create_invoice(1.25,'Description','client-order','owner-payload',42),invoice)
        method,url=session.request.call_args.args
        options=session.request.call_args.kwargs
        self.assertEqual((method,url),('POST','https://pay.xrocket.tg/tg-invoices'))
        self.assertEqual(options['headers']['Rocket-Pay-Key'],'fake-test-key')
        self.assertNotIn('Authorization',options['headers'])
        self.assertEqual(options['json'],{'amount':1.25,'currency':'USDT','numPayments':1,'description':'Description','payload':'owner-payload','expiredIn':3600,'commentsEnabled':False})
        session.request.assert_called_once()

    async def test_xrocket_get_contract_follows_explicit_mode(self):
        for mode,url,params in [('exchange','https://pay.api.xrocket.exchange/api/v1/invoice',{'invoiceId':'12'}),('tg','https://pay.xrocket.tg/tg-invoices/12',None)]:
            with self.subTest(mode=mode):
                _,session,_=self.response(xrocket,{'success':True,'data':{'id':12,'status':'paid'}})
                with patch.dict(os.environ,{'XROCKET_API_MODE':mode}),patch.object(xrocket,'XROCKET_API_KEY','fake'):
                    self.assertEqual((await xrocket.get_invoice('12'))['id'],12)
                self.assertEqual(session.request.call_args.args,('GET',url))
                self.assertEqual(session.request.call_args.kwargs['params'],params)

    async def test_crypto_create_uses_fiat_rub_and_exact_owner_payload(self):
        invoice={'invoice_id':12,'bot_invoice_url':'https://t.me/fixture'}
        _,session,_=self.response(cryptopay,{'ok':True,'result':invoice})
        with patch.object(cryptopay,'CRYPTO_PAY_TOKEN','fake'):
            self.assertEqual(await cryptopay.create_invoice(123.45,'Description','owner-payload'),invoice)
        self.assertEqual(session.request.call_args.args,('POST','https://pay.crypt.bot/api/createInvoice'))
        options=session.request.call_args.kwargs
        self.assertEqual(options['headers']['Crypto-Pay-API-Token'],'fake')
        self.assertEqual(options['json']['currency_type'],'fiat')
        self.assertEqual(options['json']['fiat'],'RUB')
        self.assertEqual(options['json']['amount'],'123.45')
        self.assertEqual(options['json']['payload'],'owner-payload')
        self.assertEqual(options['json']['expires_in'],3600)

    async def test_crypto_get_selects_only_requested_invoice_from_items(self):
        _,session,_=self.response(cryptopay,{'ok':True,'result':{'items':[None,'bad',{'invoice_id':11},{'invoice_id':12,'status':'paid'}]}})
        with patch.object(cryptopay,'CRYPTO_PAY_TOKEN','fake'):
            self.assertEqual(await cryptopay.get_invoice('12'),{'invoice_id':12,'status':'paid'})
        self.assertEqual(session.request.call_args.kwargs['params'],{'invoice_ids':'12','count':1})

    async def test_http_errors_never_accept_paid_body_or_log_response_secrets(self):
        for module,variable in [(xrocket,'XROCKET_API_KEY'),(cryptopay,'CRYPTO_PAY_TOKEN'),(lavepay,'LAVE_PAY_API_KEY')]:
            with self.subTest(provider=module.__name__):
                response,session,_=self.response(module,{'ok':True,'data':{'status':'paid','payload':'PRIVATE_SECRET'}},status=500)
                with patch.object(module,variable,'fake'),patch.dict(os.environ,{'XROCKET_API_MODE':'exchange'}),self.assertLogs(module.logger,level='WARNING') as logs:
                    self.assertIsNone(await module._request('POST','/fixture',{}))
                response.json.assert_not_awaited()
                session.request.assert_called_once()
                self.assertNotIn('PRIVATE_SECRET',''.join(logs.output))
                self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    async def test_malformed_or_explicitly_rejected_success_envelopes_never_return_invoice(self):
        for module,variable,body in [(cryptopay,'CRYPTO_PAY_TOKEN',{'ok':'true','result':{'status':'paid'}}),(lavepay,'LAVE_PAY_API_KEY',{'ok':False,'data':{'status':'paid'}}),(xrocket,'XROCKET_API_KEY',{'success':False,'data':{'status':'paid'}})]:
            with self.subTest(provider=module.__name__):
                self.response(module,body)
                with patch.object(module,variable,'fake'),patch.dict(os.environ,{'XROCKET_API_MODE':'exchange'}):
                    self.assertIsNone(await module._request('GET','/fixture'))
        self.response(lavepay,[])
        with patch.object(lavepay,'LAVE_PAY_API_KEY','fake'):
            self.assertIsNone(await lavepay._request('GET','/fixture'))

    async def test_network_failure_is_not_retried_and_exception_text_is_redacted(self):
        for module,variable in [(xrocket,'XROCKET_API_KEY'),(cryptopay,'CRYPTO_PAY_TOKEN'),(lavepay,'LAVE_PAY_API_KEY')]:
            with self.subTest(provider=module.__name__):
                _,_,factory=self.response(module,None,error=OSError('PRIVATE_TOKEN_IN_URL'))
                with patch.object(module,variable,'fake'),patch.dict(os.environ,{'XROCKET_API_MODE':'exchange'}),self.assertLogs(module.logger,level='WARNING') as logs:
                    self.assertIsNone(await module._request('POST','/fixture',{}))
                factory.assert_called_once()
                self.assertNotIn('PRIVATE_TOKEN_IN_URL',''.join(logs.output))

    async def test_invalid_xrocket_mode_never_creates_invoice(self):
        with patch.dict(os.environ,{'XROCKET_API_MODE':'unexpected'}),patch.object(xrocket,'_request',AsyncMock()) as request:
            self.assertIsNone(await xrocket.create_invoice(1,'test','id','payload',42))
        request.assert_not_awaited()

    async def test_invalid_amounts_never_reach_any_provider(self):
        for amount in (0,-1,float('nan'),float('inf'),True,'bad'):
            with patch.object(xrocket,'_request',AsyncMock()) as x,patch.object(cryptopay,'_request',AsyncMock()) as c,patch.object(lavepay,'_request',AsyncMock()) as l:
                self.assertIsNone(await xrocket.create_invoice(amount,'test','id','payload',42))
                self.assertIsNone(await cryptopay.create_invoice(amount,'test','payload'))
                self.assertIsNone(await lavepay.create_invoice(amount,'test','id','payload'))
                x.assert_not_awaited();c.assert_not_awaited();l.assert_not_awaited()

    def test_only_paid_status_in_dictionary_counts_as_paid(self):
        for module in (xrocket,cryptopay,lavepay):
            self.assertTrue(module.is_paid({'status':'paid'}))
            for invoice in (None,[],{'status':'active'},{'status':'expired'},{'status':'partially_paid'}):
                self.assertFalse(module.is_paid(invoice))
