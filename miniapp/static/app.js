'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const tg = window.Telegram?.WebApp;
  const state = { tab: 'catalog', ready: false, me: null, items: [], page: 0, category: '', orderPage: 0, orders: [], busy: false, revision: 0, invoice: null, refreshing: false };
  const labels = { catalog: 'Каталог', favorites: 'Избранное', cart: 'Корзина', orders: 'Покупки', profile: 'Профиль' };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(v || 0));
  const rub = v => num(v) + ' ₽';
  const flags = { us: '🇺🇸', ru: '🇷🇺', kz: '🇰🇿', ua: '🇺🇦', gb: '🇬🇧', de: '🇩🇪', fr: '🇫🇷', in: '🇮🇳', tr: '🇹🇷', uz: '🇺🇿', nl: '🇳🇱', ca: '🇨🇦', pl: '🇵🇱', br: '🇧🇷' };
  let toastTimer, searchTimer;
  function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500); }
  function notice(text = '') { $('#notice').textContent = text; $('#notice').hidden = !text; }
  function reset(text) {
    state.ready = false; state.me = null; state.items = []; state.orders = []; state.invoice = null; state.revision++;
    $('#header-balance').textContent = '— ₽'; $('#profile-balance').textContent = '— ₽'; $('#catalog-grid').replaceChildren(); $('#orders-list').replaceChildren();
    document.querySelectorAll('.page').forEach(el => { el.hidden = true; }); $('#login-panel').hidden = false;
    $('#purchase-dialog').close(); $('#dialog-content').replaceChildren(); $('#sync-state').textContent = 'Нужен вход'; notice(text);
  }
  async function api(path, options = {}) {
    const raw = tg?.initData;
    if (!raw) { const e = new Error('Открой приложение через меню Telegram-бота.'); e.code = 'unauthorized'; throw e; }
    const res = await fetch('/api/' + path, { ...options, headers: { Authorization: 'tma ' + raw, ...(options.body ? { 'Content-Type': 'application/json' } : {}) }, cache: 'no-store', signal: AbortSignal.timeout(15000) });
    const data = await res.json();
    if (!res.ok) { const e = new Error(data.error || 'Не удалось выполнить запрос.'); e.code = data.code; throw e; }
    return data;
  }
  const post = (path, body, method = 'POST') => api(path, { method, body: JSON.stringify(body) });
  function error(e) { if (e.code === 'unauthorized') reset(e.message); else notice(e.message || 'Проверь соединение и попробуй ещё раз.'); }
  function openBot(id) {
    const username = state.me?.bot_username;
    if (!username || !/^[a-zA-Z0-9_]+$/.test(username)) { toast('Открой Telegram-бота, из которого запущен магазин.'); return; }
    const url = 'https://t.me/' + username + (id ? '?start=order_' + id : '');
    if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank', 'noopener,noreferrer');
  }
  async function loadMe() {
    const data = await api('me'); state.me = data;
    const initial = (data.user.first_name || 'S').slice(0, 1).toUpperCase();
    $('#avatar').textContent = initial; $('#profile-avatar').textContent = initial;
    $('#profile-name').textContent = data.user.first_name || 'Покупатель'; $('#profile-username').textContent = data.user.username ? '@' + data.user.username : 'Покупатель Sband ACCS';
    $('#profile-id').textContent = data.user.id; $('#header-balance').textContent = rub(data.balance); $('#profile-balance').textContent = rub(data.balance);
    $('#profile-usdt').textContent = num(data.balance_usdt) + ' USDT'; $('#version').textContent = 'v' + data.version;
  }
  function render() {
    $('#catalog-grid').innerHTML = state.items.map(item => `<article class="account-card"><div class="card-head"><span class="flag" aria-hidden="true">${flags[item.category] || '✳'}</span><div class="card-head-right"><span class="stock-tag ${item.available ? '' : 'unavailable'}">${item.available ? 'В наличии' : 'Недоступен'}</span><button class="heart ${item.favorite ? 'selected' : ''}" data-favorite="${item.id}" aria-label="${item.favorite ? 'Убрать из избранного' : 'В избранное'}" aria-pressed="${item.favorite}">${item.favorite ? '♥' : '♡'}</button></div></div><h3>${esc(item.name)}</h3><div class="card-phone">${esc(item.phone)}</div><div class="ids"><div><span>ID товара</span><b>${esc(item.product_id)}</b></div><div><span>Telegram ID</span><b>${esc(item.telegram_user_id || 'Не сохранён')}</b></div></div><div class="card-bottom"><div>${Number(item.discount) > 0 ? `<span class="old-price"><s>${rub(item.original_price)}</s><span class="discount-badge">−${num(item.discount)}%</span></span>` : ''}<span class="card-price">${num(item.price)}<small>₽</small></span></div><button class="buy-button ${item.in_cart ? 'added' : ''}" data-add="${item.id}" ${!item.available ? 'disabled' : ''} aria-label="${item.in_cart ? 'Обновить резерв' : 'В корзину'} ${esc(item.name)}">${item.in_cart ? '✓' : '+'}</button></div>${item.in_cart ? `<div class="reserve" data-until="${esc(item.reserved_until || '')}"></div><button class="remove-button" data-remove="${item.id}">Убрать из корзины</button>` : ''}</article>`).join('');
    $('#catalog-empty').hidden = state.items.length > 0;
    const empty = state.tab === 'cart' ? ['Корзина пока пуста', 'Добавь аккаунт — он будет зарезервирован на 5 минут.'] : state.tab === 'favorites' ? ['Сохрани то, что нравится', 'Нажми ♡ в каталоге. О снижении цены сообщим в боте.'] : ['Пока ничего не найдено', 'Попробуй изменить фильтры или загляни позже.'];
    $('#empty-title').textContent = empty[0]; $('#empty-copy').textContent = empty[1];
    $('#cart-summary').hidden = state.tab !== 'cart' || !state.items.length;
    $('#cart-count').textContent = `· ${state.items.length} шт.`;
    // Integer kopecks keep the displayed quote equal to the server's Decimal total.
    $('#cart-total').textContent = rub(state.items.reduce((n, item) => n + Math.round(Number(item.price) * 100), 0) / 100);
    countdown();
  }
  function countdown() {
    document.querySelectorAll('[data-until]').forEach(el => {
      const seconds = Math.max(0, Math.floor((Date.parse(el.dataset.until) - Date.now()) / 1000));
      el.textContent = seconds ? `Резерв ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : 'Резерв истёк · нажми ✓, чтобы обновить';
    });
    if (state.tab === 'cart') $('#checkout-cart').disabled = !state.items.length || state.items.some(i => !i.available || !(Date.parse(i.reserved_until) > Date.now()));
  }
  async function loadMarket(append = false) {
    if (!['catalog', 'favorites', 'cart'].includes(state.tab)) return;
    const rev = ++state.revision, tab = state.tab, page = append ? state.page + 1 : 0;
    const query = new URLSearchParams({ page });
    if (tab === 'catalog') { query.set('category', state.category); query.set('q', $('#search').value); query.set('sort', $('#sort').value); query.set('min_price', $('#min-price').value); query.set('max_price', $('#max-price').value); }
    const data = await api((tab === 'catalog' ? 'catalog' : tab) + '?' + query);
    if (rev !== state.revision || state.tab !== tab || !state.ready) return;
    state.page = page; state.items = append ? [...state.items, ...data.items] : data.items;
    $('#total-count').textContent = tab === 'catalog' ? data.categories.reduce((n, c) => n + Number(c.count), 0) : state.items.length;
    $('#categories').innerHTML = [{ slug: '', name: 'Все аккаунты', count: data.categories.reduce((n, c) => n + Number(c.count), 0) }, ...data.categories].map(c => `<button class="category ${c.slug === state.category ? 'active' : ''}" data-category="${esc(c.slug)}">${esc(c.name)}<small>${c.count}</small></button>`).join('');
    $('#load-more').hidden = !data.has_more; render();
  }
  async function loadOrders(append = false) {
    const page = append ? state.orderPage + 1 : 0, data = await api('orders?page=' + page);
    if (!state.ready) return;
    state.orderPage = page; state.orders = append ? [...state.orders, ...data.items] : data.items;
    $('#orders-list').innerHTML = state.orders.map(o => `<article class="order-row"><div><h3>${esc(o.name)} · #${o.id}</h3><p>${esc(o.status_label)} · ${esc(o.date)}<br>${o.paid_amount !== null ? num(o.paid_amount) + ' ' + esc(o.currency) : 'Сумма не сохранена'}</p></div><button data-order="${o.id}">Открыть <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button></article>`).join('');
    $('#orders-empty').hidden = state.orders.length > 0; $('#more-orders').hidden = !data.has_more;
  }
  function showPage() {
    $('#market-page').hidden = !['catalog', 'favorites', 'cart'].includes(state.tab);
    $('#orders-page').hidden = state.tab !== 'orders'; $('#profile-page').hidden = state.tab !== 'profile';
    document.querySelectorAll('[data-tab]').forEach(el => el.classList.toggle('active', el.dataset.tab === state.tab));
    $('#breadcrumb').textContent = labels[state.tab]; $('#hero').hidden = state.tab !== 'catalog'; $('#benefits').hidden = state.tab !== 'catalog'; $('#filters').hidden = state.tab !== 'catalog';
    $('#market-title').textContent = state.tab === 'catalog' ? 'Каталог аккаунтов' : labels[state.tab];
    $('#market-kicker').textContent = state.tab === 'cart' ? 'РЕЗЕРВ НА 5 МИНУТ' : state.tab === 'favorites' ? 'ТО, ЧТО НРАВИТСЯ' : 'ВЫБЕРИ СВОЙ';
    $('#collection-note').hidden = state.tab === 'catalog';
    $('#collection-note').textContent = state.tab === 'cart' ? 'Оплата всей корзины за один раз. После истечения резерва нажми ✓ на каждом аккаунте.' : 'Сообщим в боте, если базовая цена снизится. Убери ♡, чтобы отключить уведомления.';
  }
  async function switchTab(tab) {
    if (!state.ready || !labels[tab]) return;
    state.tab = tab; state.revision++; state.page = 0; state.items = []; showPage(); notice();
    $('#catalog-grid').replaceChildren(); $('#cart-summary').hidden = true;
    try { if (tab === 'orders') await loadOrders(); else if (tab !== 'profile') await loadMarket(); } catch (e) { error(e); }
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function modal(html) { $('#dialog-content').innerHTML = html; if (!$('#purchase-dialog').open) $('#purchase-dialog').showModal(); }
  function dialogError(e) { if (e.code === 'unauthorized') { reset(e.message); return; } const el = $('#dialog-error'); if (el) { el.textContent = e.message; el.hidden = false; } else error(e); }
  async function checkout() {
    if (!state.items.length || state.busy) return;
    const items = state.items.map(i => ({ account_id: i.id, price: i.price }));
    const total = items.reduce((n, i) => n + Math.round(Number(i.price) * 100), 0) / 100;
    modal(`<h2 id="dialog-title">Подтвердить покупку</h2><p>${items.length} аккаунт(ов). После оплаты они появятся в покупках и Telegram-боте.</p><div class="info"><span>К оплате</span><b>${rub(total)}</b></div><div class="info"><span>Баланс</span><b>${rub(state.me.balance)}</b></div><p id="dialog-error" class="dialog-error" role="alert" hidden></p><button id="confirm-purchase" class="primary-button">Оплатить ${rub(total)} <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
    $('#confirm-purchase').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#confirm-purchase').disabled = true;
      try {
        const result = await post('cart/checkout', { items });
        modal(`<div class="success-icon">✓</div><h2 id="dialog-title">Покупка готова!</h2><p>Заказов: ${result.order_ids.length}. Списано ${rub(result.paid_amount)}.<br>Остаток: ${rub(result.balance)}.</p><button class="primary-button" id="show-my-orders">Мои покупки <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
        $('#show-my-orders').onclick = () => { $('#purchase-dialog').close(); switchTab('orders'); };
        tg?.HapticFeedback?.notificationOccurred('success'); await loadMe(); await loadMarket();
      } catch (e) { dialogError(e); if ($('#confirm-purchase')) { $('#confirm-purchase').disabled = ['sold', 'price_changed', 'reservation_expired', 'cart_changed'].includes(e.code); } await loadMarket().catch(() => {}); }
      finally { state.busy = false; }
    };
  }
  async function showOrder(id) {
    try {
      const o = await api('orders/' + id);
      modal(`<h2 id="dialog-title">Заказ #${o.id}</h2><p>${esc(o.status_label)} · ${esc(o.date)}</p><div class="info"><span>ID товара</span><b>${esc(o.product_id || '—')}</b></div><div class="info"><span>Telegram ID</span><b>${esc(o.telegram_user_id || 'Не сохранён')}</b></div><div class="info"><span>Номер</span><b class="secret-value">${esc(o.number || '—')}</b></div><div class="info"><span>Пароль 2FA</span><b class="secret-value" id="order-password">${o.status === 'refunded' ? 'Доступ закрыт' : '••••••'}</b></div>${o.status !== 'refunded' ? '<button id="show-password" class="secondary-button">Показать пароль</button>' : ''}<p>Код входа, завершение покупки и поддержка доступны в Telegram-боте.</p><button class="primary-button" data-bot-order="${o.id}">Открыть в боте <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
      if ($('#show-password')) $('#show-password').onclick = () => { $('#order-password').textContent = o.password || 'Не установлен'; $('#show-password').hidden = true; };
    } catch (e) { error(e); }
  }
  async function topup() {
    if (!state.ready || state.busy) return;
    if (state.invoice) { showInvoice(); return; }
    try {
      const data = await api('payment-methods'), methods = data.items.filter(m => m.enabled);
      if (!methods.length) { modal('<h2 id="dialog-title">Пополнение баланса</h2><p>Платёжные сервисы пока не настроены. Обратись к администратору через Telegram-бота.</p><button class="primary-button" data-bot>Открыть бота <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>'); return; }
      modal(`<h2 id="dialog-title">Пополнить баланс</h2><p>Оплата подтвердится автоматически, обычно в течение минуты после подтверждения сервисом.</p><label for="topup-amount">Сумма, ₽</label><input id="topup-amount" type="number" inputmode="decimal" min="10" max="1000000" step="0.01" value="500"><label for="topup-method">Способ оплаты</label><select id="topup-method">${methods.map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</select><p id="dialog-error" class="dialog-error" role="alert" hidden></p><button class="primary-button" id="create-invoice">Создать счёт <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
      $('#create-invoice').onclick = async () => {
        if (state.busy) return; state.busy = true; $('#create-invoice').disabled = true;
        try { state.invoice = await post('invoices', { amount: $('#topup-amount').value, provider: $('#topup-method').value }); showInvoice(); }
        catch (e) { dialogError(e); if ($('#create-invoice')) $('#create-invoice').disabled = false; }
        finally { state.busy = false; }
      };
    } catch (e) { error(e); }
  }
  function showInvoice() {
    const i = state.invoice; if (!i) return;
    const url = new URL(i.pay_url); if (url.protocol !== 'https:') return;
    modal(`<h2 id="dialog-title">Счёт на ${rub(i.amount)}</h2><p>Перейди к оплате. Баланс обновится автоматически после подтверждения платёжным сервисом.</p><a class="payment-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">Перейти к оплате <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></a><p id="invoice-state">Ожидаем оплату…</p><p>Можно закрыть это окно: проверка продолжится на сервере.</p><button id="another-invoice" class="secondary-button">Создать другой счёт</button>`);
    $('#another-invoice').onclick = () => { state.invoice = null; topup(); };
  }
  async function checkInvoice() {
    const i = state.invoice; if (!i) return;
    const data = await api('invoices/' + encodeURIComponent(i.provider) + '/' + encodeURIComponent(i.invoice_id));
    if (state.invoice !== i) return;
    if (data.status === 'credited') { state.invoice = null; await loadMe(); if ($('#invoice-state')) $('#invoice-state').textContent = '✓ Оплата подтверждена. Баланс пополнен!'; toast('Баланс пополнен автоматически'); }
    else if (data.status === 'expired') { state.invoice = null; if ($('#invoice-state')) $('#invoice-state').textContent = 'Срок счёта истёк. Создай новый счёт.'; }
  }
  async function synchronize() {
    if (!state.ready || state.busy || state.refreshing || document.hidden) return;
    state.refreshing = true;
    try { await Promise.all([loadMe(), state.tab === 'orders' ? loadOrders() : loadMarket(), checkInvoice()]); $('#sync-state').textContent = '● Обновлено сейчас'; }
    catch (e) { $('#sync-state').textContent = 'Нет обновления'; if (e.code === 'unauthorized') reset(e.message); }
    finally { state.refreshing = false; }
  }
  async function initialize() {
    try { tg?.ready(); tg?.expand(); tg?.setHeaderColor('#101510'); tg?.setBackgroundColor('#101510'); await loadMe(); state.ready = true; $('#login-panel').hidden = true; notice(); showPage(); await loadMarket(); $('#sync-state').textContent = '● Обновлено сейчас'; }
    catch (e) { reset(e.message); }
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    if (button.dataset.tab) { switchTab(button.dataset.tab); return; }
    if (button.hasAttribute('data-bot')) openBot();
    if (button.dataset.botOrder) openBot(Number(button.dataset.botOrder));
    if (button.dataset.order) showOrder(Number(button.dataset.order));
    if (button.hasAttribute('data-topup')) topup();
    if (button.hasAttribute('data-category')) { state.category = button.dataset.category; loadMarket().catch(error); }
    if (button.dataset.add || button.dataset.favorite || button.dataset.remove) {
      const id = Number(button.dataset.add || button.dataset.favorite || button.dataset.remove), item = state.items.find(i => i.id === id); if (!item) return;
      button.disabled = true;
      try {
        if (button.dataset.add) { await post('cart', { account_id: id }); toast(item.in_cart ? 'Резерв проверен' : 'В корзине · резерв на 5 минут'); }
        else if (button.dataset.remove) await post('cart', { account_id: id }, 'DELETE');
        else { await post('favorites', { account_id: id, enabled: !item.favorite }); toast(item.favorite ? 'Удалено из избранного' : 'Сохранено · о снижении цены сообщим в боте'); }
        await loadMarket();
      } catch (e) { error(e); button.disabled = false; }
    }
  });
  $('#checkout-cart').onclick = checkout;
  $('#close-dialog').onclick = () => { if (!state.busy) $('#purchase-dialog').close(); };
  $('#purchase-dialog').addEventListener('cancel', e => { if (state.busy) e.preventDefault(); });
  $('#purchase-dialog').addEventListener('close', () => $('#dialog-content').replaceChildren());
  for (const id of ['search', 'min-price', 'max-price']) $('#' + id).addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { if (state.ready) loadMarket().catch(error); }, 300); });
  $('#sort').onchange = () => loadMarket().catch(error);
  $('#load-more').onclick = async () => { $('#load-more').disabled = true; try { await loadMarket(true); } catch (e) { error(e); } finally { $('#load-more').disabled = false; } };
  $('#more-orders').onclick = async () => { $('#more-orders').disabled = true; try { await loadOrders(true); } catch (e) { error(e); } finally { $('#more-orders').disabled = false; } };
  $('#refresh').onclick = () => loadMarket().then(() => notice()).catch(error); $('#refresh-orders').onclick = () => loadOrders().catch(error); $('#retry-login').onclick = initialize;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) synchronize(); }); window.addEventListener('online', synchronize);
  window.addEventListener('offline', () => notice('Нет соединения. Подключись к интернету, чтобы обновить данные.'));
  setInterval(countdown, 1000); setInterval(synchronize, 15000); initialize();
})();
