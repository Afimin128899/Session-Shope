"""Private in-memory training store. No DB, Telegram clients or payment providers."""
from collections import OrderedDict
from decimal import Decimal, InvalidOperation
import secrets
import time

LIMIT=128


def cash(value):
    return f'{Decimal(value)/100:.2f}'


def amount(value):
    try:
        if isinstance(value,bool) or len(str(value))>24: raise ValueError
        number=Decimal(str(value).replace(',','.'))
        if not number.is_finite() or not Decimal(10)<=number<=Decimal(10000) or number!=number.quantize(Decimal('.01')): raise ValueError
        return int(number*100)
    except (ValueError,InvalidOperation):
        raise ValueError('Учебное пополнение: 10–10 000 ₽, до двух знаков после запятой.') from None


class DemoStore:
    def __init__(self):
        self.states=OrderedDict()

    def active(self,user):
        return bool(self.states.get(user,{}).get('active'))

    def _state(self,user):
        if user not in self.states:
            if len(self.states)>=LIMIT:
                victim=next((key for key,value in self.states.items() if not value['active']),None)
                if victim is None:raise ValueError('Все учебные сессии заняты. Завершите старую сессию.')
                del self.states[victim]
            self.states[user]={'generation':secrets.token_hex(4),'active':False,'balance':100000,
                'products':[{'id':i,'name':f'Учебный аккаунт {i}','price':(50+i*50)*100,'available':True} for i in range(1,7)],
                'orders':[], 'cart':[], 'invoices':[], 'paid':0,'funding':[],'reward_at':None,'events':[]}
        self.states.move_to_end(user)
        return self.states[user]

    def _event(self,s,text):
        s['events']=(s['events']+[text])[-30:]

    def _reward_ready(self,s):
        now=time.time()
        paid=sum(amount for amount,stamp in s['funding'] if stamp>now-259200)
        return paid>=5000 and (s['reward_at'] is None or now-s['reward_at']>=259200)

    def view(self,user):
        s=self._state(user)
        return {'test_mode':True,'generation':s['generation'],'active':s['active'],'balance':cash(s['balance']),
            'products':[dict(p,price=cash(p['price'])) for p in s['products']],
            'cart':list(s['cart']), 'orders':[dict(o,paid=cash(o['paid'])) for o in s['orders']],
            'invoices':[dict(i,amount=cash(i['amount'])) for i in s['invoices'][-10:]],
            'reward_available':self._reward_ready(s),
            'events':list(s['events'])}

    def enter(self,user):
        self._state(user)['active']=True
        return self.view(user)

    def exit(self,user):
        if user in self.states:self.states[user]['active']=False

    def action(self,user,body):
        s=self._state(user)
        if not s['active']: raise ValueError('Откройте тестовый режим заново.')
        if body.get('generation')!=s['generation']:raise ValueError('Тестовый сценарий обновлён. Обновите экран.')
        action=body.get('action')
        if not isinstance(action,str):raise ValueError('Некорректное учебное действие.')
        if action=='reset':
            del self.states[user]
            return self.enter(user)
        if action=='exit':
            self.exit(user);return self.view(user)
        if action in {'add','remove','buy'}:
            identity=body.get('id')
            if type(identity)is not int:raise ValueError('Выберите учебный товар.')
            product=next((p for p in s['products'] if p['id']==identity),None)
            if not product:raise ValueError('Учебный товар не найден.')
            if action=='remove':
                s['cart']=[i for i in s['cart'] if i!=identity]
            elif not product['available']:raise ValueError('Учебный товар уже куплен.')
            elif action=='add':
                if identity not in s['cart']:s['cart'].append(identity)
            else:self._buy(s,[identity],body.get('promo',''))
        elif action=='checkout':self._buy(s,list(s['cart']),body.get('promo',''))
        elif action=='invoice':
            provider=body.get('provider')
            if not isinstance(provider,str) or provider not in {'crypto','xrocket','lave','platega','stars'}:raise ValueError('Выберите учебный способ оплаты.')
            if provider=='stars':
                count=body.get('stars')
                if type(count)is not int or not 1<=count<=8333:raise ValueError('Звёзды: целое число 1–8333.')
                total=count*120
            else:total=amount(body.get('amount'))
            if len(s['invoices'])>=100:raise ValueError('Сбросьте учебный сценарий: достигнут лимит счетов.')
            s['invoices'].append({'id':secrets.token_hex(8),'provider':provider,'amount':total,'paid':False})
            self._event(s,'Создан учебный счёт.')
        elif action=='pay':
            invoice=next((i for i in s['invoices'] if i['id']==body.get('invoice_id')),None)
            if not invoice:raise ValueError('Учебный счёт не найден.')
            if not invoice['paid']:
                if s['balance']+invoice['amount']>100000000:raise ValueError('Достигнут лимит учебного баланса.')
                invoice['paid']=True;s['balance']+=invoice['amount'];s['paid']+=invoice['amount'];s['funding'].append((invoice['amount'],time.time()))
                self._event(s,'Учебная оплата подтверждена: +'+cash(invoice['amount'])+' ₽.')
        elif action in {'refund','complete','code'}:
            identity=body.get('id')
            if type(identity)is not int:raise ValueError('Выберите учебный заказ.')
            order=next((o for o in s['orders'] if o['id']==identity),None)
            if not order:raise ValueError('Учебный заказ не найден.')
            if action=='refund' and order['status']!='refunded':
                s['balance']+=order['paid'];order['status']='refunded'
                self._event(s,f'Учебный возврат #{identity}: +{cash(order["paid"])} ₽.')
            elif action=='complete' and order['status']=='issued':order['status']='completed'
            elif action=='code':
                if order['status']!='issued':raise ValueError('Учебный заказ закрыт.')
                self._event(s,f'Учебный код заказа #{identity}: TEST-{identity:06d}.')
        elif action=='reward':
            if not self._reward_ready(s):raise ValueError('Для учебного колеса нужно пополнить от 50 ₽; повтор — раз в 3 дня.')
            reward=(secrets.randbelow(10)+1)*100;s['balance']+=reward;s['reward_at']=time.time()
            self._event(s,'Учебный бонус: +'+cash(reward)+' ₽.')
        else:raise ValueError('Действие недоступно в тестовом режиме.')
        return self.view(user)

    def _buy(self,s,ids,promo):
        if not ids:raise ValueError('Учебная корзина пуста.')
        if not isinstance(promo,str) or promo.strip().upper() not in {'','DEMO10'}:raise ValueError('Для учебной скидки используйте DEMO10.')
        products=[p for p in s['products'] if p['id'] in ids]
        if len(products)!=len(ids) or any(not p['available'] for p in products):raise ValueError('Учебный товар недоступен.')
        prices=[p['price']*90//100 if promo.strip() else p['price'] for p in products]
        total=sum(prices)
        if s['balance']<total:raise ValueError('Недостаточно учебных средств.')
        s['balance']-=total
        for product,price in zip(products,prices):
            product['available']=False
            s['orders'].append({'id':len(s['orders'])+1,'product_id':product['id'],'name':product['name'],'paid':price,'status':'issued'})
        s['cart']=[i for i in s['cart'] if i not in ids]
        self._event(s,'Учебная покупка: −'+cash(total)+' ₽.')


STORE=DemoStore()
