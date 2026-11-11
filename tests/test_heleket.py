"""Official Heleket SDK wire contract and fail-closed settlement, entirely offline."""
import base64
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from test_payments import config, db
from services import heleket, payments
from database import commerce

IDENTITY = '11111111-1111-4111-8111-111111111111'
ROW = {'provider':'heleket', 'invoice_id':IDENTITY, 'user_id':42, 'amount_rub':Decimal('50.00'), 'status':'pending'}
PAID = {'uuid':IDENTITY, 'id':IDENTITY, 'status':'paid', 'is_final':True, 'amount':'50.00',
        'currency':'RUB', 'additional_data':'rub_topup:42:50.00', 'payload':'rub_topup:42:50.00'}


class HeleketTests(unittest.IsolatedAsyncioTestCase):
    def wire(self, body, status=200):
        reply = NS(status=status, json=AsyncMock(return_value=body))
        context = MagicMock(); context.__aenter__.return_value = reply
        session = NS(request=MagicMock(return_value=context))
        factory = MagicMock(); factory.return_value.__aenter__.return_value = session
        p = patch.object(heleket.aiohttp, 'ClientSession', factory); p.start(); self.addCleanup(p.stop)
        for name, value in [('HELEKET_MERCHANT_ID', IDENTITY), ('HELEKET_PAYMENT_KEY', 'fixture-key')]:
            p = patch.object(config, name, value, create=True); p.start(); self.addCleanup(p.stop)
        return reply, session

    async def test_exact_utf8_bytes_are_signed_and_sent_to_official_endpoint(self):
        _, session = self.wire({'state':0, 'result':{'uuid':IDENTITY, 'url':'https://pay.heleket.com/fixture'}})
        result = await heleket.create_invoice('50.00', 'order-42', 'rub_topup:42:50.00')
        self.assertEqual(result['id'], IDENTITY)
        self.assertEqual(session.request.call_args.args, ('POST','https://api.heleket.com/v1/payment'))
        kwargs = session.request.call_args.kwargs
        body = kwargs['data']; data = json.loads(body)
        self.assertEqual(data['amount'], '50.00'); self.assertEqual(data['currency'], 'RUB')
        self.assertEqual(data['order_id'], 'order-42'); self.assertEqual(data['additional_data'], 'rub_topup:42:50.00')
        self.assertEqual(kwargs['headers']['sign'], hashlib.md5(base64.b64encode(body) + b'fixture-key').hexdigest())
        self.assertEqual(kwargs['headers']['merchant'], IDENTITY)
        self.assertFalse(kwargs['allow_redirects'])

    async def test_polling_is_signed_post_by_uuid_and_normalises_correlation(self):
        _, session = self.wire({'state':0, 'result':PAID})
        result = await heleket.get_invoice(IDENTITY)
        self.assertEqual(result['payload'], 'rub_topup:42:50.00')
        self.assertEqual(session.request.call_args.args, ('POST','https://api.heleket.com/v1/payment/info'))
        self.assertEqual(json.loads(session.request.call_args.kwargs['data']), {'uuid':IDENTITY})
        with patch.object(heleket, '_request', AsyncMock(return_value={'uuid':'22222222-2222-4222-8222-222222222222'})):
            self.assertIsNone(await heleket.get_invoice(IDENTITY))

    async def test_http_failure_and_rejected_envelope_cannot_become_payments(self):
        for status, body in [(500,{'state':0,'result':PAID}),(200,{'state':1,'result':PAID}),(200,{'state':False,'result':PAID}),(200,{'state':0,'result':[]})]:
            reply, _ = self.wire(body, status)
            self.assertIsNone(await heleket.get_invoice(IDENTITY))
            if status == 500: reply.json.assert_not_awaited()

    async def test_creation_limits_and_configured_provider_registration(self):
        for value in ['49.99','50.001','NaN','1000000.01']:
            with self.subTest(value=value), self.assertRaises(ValueError): payments.parse_amount(value, 'heleket')
        with patch.object(config,'HELEKET_MERCHANT_ID',IDENTITY,create=True), patch.object(config,'HELEKET_PAYMENT_KEY','fixture',create=True), patch.object(heleket,'create_invoice',AsyncMock(return_value={'id':IDENTITY,'pay_url':'https://pay.heleket.com/fixture'})) as create, patch.object(commerce,'register_invoice',AsyncMock()) as register, patch.object(payments,'_health',AsyncMock()):
            result = await payments.create_deposit(42, 'fixture', 'heleket', '50')
            self.assertEqual(result['provider'], 'heleket')
            self.assertEqual(create.call_args.args[0], Decimal('50'))
            register.assert_awaited_once_with('heleket', IDENTITY, 42, Decimal('50'))

    async def test_only_final_paid_exact_owner_amount_currency_and_uuid_can_credit(self):
        variants = [PAID | {'currency':'USD'}, PAID | {'amount':'49.99'}, PAID | {'amount':'NaN'},
                    PAID | {'payload':'rub_topup:43:50.00'}, PAID | {'id':'foreign'}, PAID | {'payload':'broken'}]
        with patch.object(db,'credit_paid_deposit',AsyncMock()) as credit:
            for invoice in variants:
                with self.subTest(invoice=invoice), self.assertRaises(ValueError): await payments.settle_invoice(ROW, invoice)
            for invoice in [PAID | {'is_final':False}, PAID | {'status':'confirm_check'}, PAID | {'status':'wrong_amount'}]:
                self.assertIsNone(await payments.settle_invoice(ROW, invoice))
            credit.assert_not_awaited()
        with patch.object(db,'credit_paid_deposit',AsyncMock(return_value=(55,5))) as credit, patch.object(commerce,'finish_invoice',AsyncMock()):
            await payments.settle_invoice(ROW, PAID | {'status':'paid_over','payer_amount':'1000000'})
            credit.assert_awaited_once_with(42, Decimal('50.00'), 'heleket', IDENTITY)
