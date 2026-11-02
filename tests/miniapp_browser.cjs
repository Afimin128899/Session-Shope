// Real API and disposable MariaDB; only Telegram SDK is stubbed.
const { chromium } = require('playwright');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const token = '123456:local-test-token-not-for-production';
const values = { auth_date: String(Math.floor(Date.now() / 1000)), query_id: 'browser-test', user: JSON.stringify({ id: 42, first_name: 'Александр', username: 'alex_test' }) };
const key = crypto.createHmac('sha256', 'WebAppData').update(token).digest();
values.hash = crypto.createHmac('sha256', key).update(Object.keys(values).sort().map(k => k + '=' + values[k]).join('\n')).digest('hex');
const initData = new URLSearchParams(values).toString();
const output = process.env.MINIAPP_SCREENSHOT_DIR || '/tmp/session-miniapp-preview';
fs.mkdirSync(output, { recursive: true });
(async () => {
 const browser = await chromium.launch({ executablePath: '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
 const errors = [];
 async function context(viewport, authenticated = true) {
  const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await ctx.route('https://telegram.org/**', route => route.abort());
  if (authenticated) await ctx.addInitScript(raw => {
   window.Telegram = { WebApp: { initData: raw, ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, openTelegramLink() {}, HapticFeedback: { notificationOccurred() {} } } };
  }, initData);
  const page = await ctx.newPage(); page.on('pageerror', e => errors.push(e.message)); await page.goto('http://127.0.0.1:8085'); return { ctx, page };
 }
 try {
  const desktop = await context({ width: 1440, height: 1000 }), p = desktop.page;
  await p.waitForSelector('.account-card');
  assert.equal(await p.locator('.account-card').count(), 12);
  assert.equal(await p.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert((await p.locator('.ids').first().innerText()).includes('Telegram ID'));
  await p.screenshot({ path: path.join(output, 'miniapp-desktop.png'), fullPage: true });
  await p.locator('#search').fill('Россия'); await p.waitForFunction(() => document.querySelectorAll('.account-card').length === 2);
  await p.locator('#search').fill('8880000002'); await p.waitForFunction(() => document.querySelectorAll('.account-card').length === 1);
  assert((await p.locator('.ids').innerText()).includes('8880000002'));
  await p.locator('#search').fill(''); await p.waitForFunction(() => document.querySelectorAll('.account-card').length === 12);
  await p.locator('#max-price').fill('100'); await p.waitForFunction(() => document.querySelectorAll('.account-card').length === 1);
  await p.locator('#max-price').fill(''); await p.waitForFunction(() => document.querySelectorAll('.account-card').length === 12);
  await p.locator('.heart').first().click(); await p.waitForSelector('.heart.selected');
  await p.locator('.side-nav [data-tab="favorites"]').click(); await p.waitForSelector('.account-card'); assert.equal(await p.locator('.account-card').count(), 1);
  await p.locator('.buy-button').click(); await p.waitForSelector('.reserve');
  await p.locator('.side-nav [data-tab="cart"]').click(); await p.waitForSelector('#cart-summary:visible');
  assert((await p.locator('.reserve').innerText()).includes('Резерв'));
  await p.screenshot({ path: path.join(output, 'miniapp-cart-desktop.png'), fullPage: true });
  await p.locator('#checkout-cart').click(); await p.waitForSelector('#confirm-purchase'); await p.locator('#confirm-purchase').click();
  await p.waitForSelector('#show-my-orders'); await p.locator('#show-my-orders').click(); await p.waitForSelector('.order-row');
  await p.locator('[data-order]').first().click(); await p.waitForSelector('#show-password');
  assert.equal(await p.locator('#order-password').innerText(), '••••••'); await p.locator('#show-password').click();
  assert.equal(await p.locator('#order-password').innerText(), 'test'); await p.locator('#close-dialog').click();
  console.log('PASS: desktop, both ID search, price filters, favorites, reserve, actual bulk payment and owner order');
  const mobile = await context({ width: 390, height: 844 }), m = mobile.page;
  await m.waitForSelector('.account-card');
  assert.equal(await m.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await m.screenshot({ path: path.join(output, 'miniapp-mobile.png'), fullPage: true });
  await m.locator('.mobile-nav [data-tab="profile"]').click(); await m.waitForSelector('#profile-page:visible');
  assert((await m.locator('#profile-balance').innerText()).includes('₽'));
  await m.locator('.balance-panel [data-topup]').click(); await m.waitForSelector('#purchase-dialog[open]');
  assert((await m.locator('#dialog-content').innerText()).includes('пока не настроены'));
  await m.locator('#close-dialog').click(); await m.screenshot({ path: path.join(output, 'miniapp-profile-mobile.png'), fullPage: true });
  await m.locator('.mobile-nav [data-tab="catalog"]').click(); await m.waitForSelector('.account-card');
  await m.setViewportSize({ width: 320, height: 700 });
  assert.equal(await m.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  const signedOut = await context({ width: 390, height: 844 }, false);
  await signedOut.page.waitForSelector('#login-panel:visible'); assert.equal(await signedOut.page.locator('.account-card').count(), 0);
  assert.deepEqual(errors, []);
  console.log('PASS: mobile 390/320px, navigation, wallet, safe sign-in and no browser runtime errors');
 } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
