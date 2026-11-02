// Run against `python tests/integration_miniapp.py --serve` (isolated fixtures only).
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
const url = 'http://127.0.0.1:8085';
const output = process.env.MINIAPP_SCREENSHOT_DIR || '/tmp/session-miniapp-preview';
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || '/usr/bin/chromium', headless: true, args: ['--no-sandbox'] });
  const errors = [];
  async function context(viewport, authenticated = true) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1 });
    // Official SDK network is unnecessary in this isolated visual test.
    await ctx.route('https://telegram.org/**', route => route.abort());
    if (authenticated) await ctx.addInitScript(raw => {
      window.Telegram = { WebApp: { initData: raw, ready() {}, expand() {}, setHeaderColor() {}, setBackgroundColor() {}, close() {}, openTelegramLink() {}, HapticFeedback: { selectionChanged() {}, notificationOccurred() {} } } };
    }, initData);
    const page = await ctx.newPage();
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    return { ctx, page };
  }
  try {
    const desktop = await context({ width: 1440, height: 1000 });
    await desktop.page.waitForSelector('.account-card');
    assert.equal(await desktop.page.locator('.account-card').count(), 11);
    assert.equal(await desktop.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await desktop.page.screenshot({ path: path.join(output, 'miniapp-desktop.png'), fullPage: true, animations: 'disabled' });
    await desktop.page.locator('#search').fill('Россия');
    await desktop.page.waitForFunction(() => document.querySelectorAll('.account-card').length === 2);
    assert((await desktop.page.locator('.account-card h3').allTextContents()).every(t => t === 'Россия'));
    await desktop.page.locator('#search').fill('');
    await desktop.page.waitForFunction(() => document.querySelectorAll('.account-card').length === 11);
    await desktop.page.locator('[data-category="de"]').click();
    await desktop.page.waitForFunction(() => document.querySelectorAll('.account-card').length === 2);
    assert((await desktop.page.locator('.account-card h3').allTextContents()).every(t => t === 'Германия'));
    console.log('PASS: desktop rendering, search, category filter and no horizontal overflow');
    await desktop.ctx.close();

    const mobile = await context({ width: 390, height: 844 });
    await mobile.page.waitForSelector('.account-card');
    assert.equal(await mobile.page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await mobile.page.screenshot({ path: path.join(output, 'miniapp-mobile.png'), fullPage: false, animations: 'disabled' });
    await mobile.page.locator('.mobile-nav [data-tab="orders"]').click();
    await mobile.page.waitForSelector('.order-row');
    await mobile.page.locator('.order-row').first().click();
    await mobile.page.waitForSelector('#show-password');
    await mobile.page.locator('#show-password').click();
    assert.equal(await mobile.page.locator('#order-password').textContent(), 'fixture-password');
    await mobile.page.locator('#close-dialog').click();
    await mobile.page.locator('.mobile-nav [data-tab="catalog"]').click();
    await mobile.page.locator('.buy-button').first().click();
    await mobile.page.waitForSelector('#confirm-purchase');
    const purchase = mobile.page.waitForResponse(res => res.url().endsWith('/api/purchase') && res.request().method() === 'POST');
    await mobile.page.locator('#confirm-purchase').click();
    assert.equal((await purchase).status(), 201);
    await mobile.page.getByText('Аккаунт твой!').waitFor();
    await mobile.page.locator('#show-my-orders').click();
    await mobile.page.waitForFunction(() => document.querySelectorAll('.order-row').length === 2);
    await mobile.page.locator('.mobile-nav [data-tab="profile"]').click();
    await mobile.page.locator('#profile-page:not([hidden])').waitFor();
    await mobile.page.screenshot({ path: path.join(output, 'miniapp-profile.png'), fullPage: true, animations: 'disabled' });
    console.log('PASS: mobile orders, owner password reveal, real purchase, synchronized orders and profile');
    await mobile.ctx.close();

    const outside = await context({ width: 390, height: 844 }, false);
    await outside.page.locator('#login-panel:not([hidden])').waitFor();
    assert.equal(await outside.page.locator('.account-card').count(), 0);
    assert.equal(await outside.page.locator('#header-balance').textContent(), '— ₽');
    await outside.ctx.close();
    assert.deepEqual(errors, []);
    console.log('PASS: unsigned browser has no catalog or private data; no JavaScript errors');
    console.log('Screenshots saved in ' + output);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
