// Offline checks: no Telegram credentials or external requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('miniapp/static/client.js', 'utf8');
function setup(fetch, raw = 'fixture-init-data') {
  const context = {window: {Telegram: {WebApp: {initData: raw}}}, fetch, AbortController, setTimeout, clearTimeout};
  vm.runInNewContext(source, context);
  return context.window.SbandRequest;
}
(async () => {
  let calls = 0;
  const request = setup(async (url, options) => {
    calls++; assert.equal(url, '/api/cart/checkout');
    assert.equal(options.headers.Authorization, 'tma fixture-init-data');
    assert.equal(options.headers['Content-Type'], 'application/json');
    return {ok: true, status: 201, json: async () => ({id: 1})};
  });
  assert.equal((await request('cart/checkout', {method: 'POST', body: '{}'})).id, 1);
  assert.equal(calls, 1);
  for (const status of [401, 403]) {
    const req = setup(async () => ({status, json: async () => {throw Error('not JSON');}}));
    await assert.rejects(req('me'), e => e.code === (status === 401 ? 'unauthorized' : 'forbidden'));
  }
  const malformed = setup(async () => ({ok: false, status: 502, json: async () => {throw Error('HTML');}}));
  await assert.rejects(malformed('me'), e => e.code === 'invalid_response' && !e.message.includes('HTML'));
  let attempted = 0;
  const offline = setup(async () => {attempted++; throw new TypeError('Failed to fetch');});
  await assert.rejects(offline('cart/checkout', {method: 'POST', body: '{}'}), e => e.code === 'connection' && e.message.includes('Проверь результат'));
  assert.equal(attempted, 1, 'A purchase must never be automatically retried');
  const timeout = setup(async () => {throw new DOMException('Aborted', 'AbortError');});
  await assert.rejects(timeout('me'), e => e.code === 'connection' && e.message.includes('вовремя'));
  const noAuth = setup(async () => {throw Error('Must not reach fetch');}, '');
  await assert.rejects(noAuth('me'), e => e.code === 'unauthorized');
  const limited = setup(async () => ({status: 429, ok: false, json: async () => ({error: 'Wait', code: 'rate_limited'})}));
  await assert.rejects(limited('me'), e => e.code === 'rate_limited' && e.message === 'Wait');
  const zip = setup(async (_, options) => {
    assert.equal(options.headers['Content-Type'], 'application/zip');
    assert.equal(options.zip, undefined);
    return {ok: true, status: 201, json: async () => ({ok: true})};
  });
  await zip('admin/imports', {method: 'POST', body: 'fixture', zip: true});
  console.log('PASS: shared transport auth, malformed gateway replies, offline payments without retries, rate limits and ZIP headers');
})().catch(e => {console.error(e); process.exit(1);});
