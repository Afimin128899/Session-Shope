'use strict';
(() => {
  const $ = (s) => document.querySelector(s);
  const tg = window.Telegram?.WebApp;
  const state = { tab: 'catalog', me: null, items: [], categories: [], orders: [], category: '', page: 0, orderPage: 0, ready: false, catalogRequest: 0, busy: false, selected: null, botUsername: '' };
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const number = (v) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(v || 0));
  const rub = (v) => number(v) + ' ₽';
  const icon = (name) => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const flags = { us: '🇺🇸', ru: '🇷🇺', kz: '🇰🇿', ua: '🇺🇦', gb: '🇬🇧', uk: '🇬🇧', de: '🇩🇪', fr: '🇫🇷', in: '🇮🇳', tr: '🇹🇷', uz: '🇺🇿', id: '🇮🇩', nl: '🇳🇱', ca: '🇨🇦', pl: '🇵🇱', br: '🇧🇷' };
  const flag = (slug) => flags[String(slug).toLowerCase()] || '✳';
  let toastTimer, searchTimer;
  function toast(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4000); }
  function notice(message = '') { $('#notice').textContent = message; $('#notice').hidden = !message; }
  function connection(message) { $('#sync-state').innerHTML = '<span class="online-dot"></span>' + esc(message); }
  function resetAuthentication(message) {
    state.ready = false; state.me = null; state.items = []; state.orders = [];
    $('#header-balance').textContent = '— ₽'; $('#profile-balance').textContent = '— ₽';
    $('#catalog-grid').replaceChildren(); $('#orders-list').replaceChildren();
    for (const page of document.querySelectorAll('.page')) page.hidden = true;
    $('#login-panel').hidden = false; $('#purchase-dialog').close(); $('#dialog-content').replaceChildren();
    connection('Нужен вход'); if (message) notice(message);
  }
  async function api(path, options = {}) {
    const raw = window.Telegram?.WebApp?.initData;
    if (!raw) { const error = new Error('Открой приложение из меню Telegram-бота.'); error.code = 'unauthorized'; throw error; }
    let response;
    try {
      response = await fetch('/api/' + path, { ...options, headers: { Authorization: 'tma ' + raw, ...(options.body ? { 'Content-Type': 'application/json' } : {}) }, cache: 'no-store', signal: AbortSignal.timeout(15000) });
    } catch { throw new Error('Не удалось подключиться. Проверь интернет и попробуй ещё раз.'); }
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || 'Не удалось выполнить запрос.'); error.code = data.code; throw error; }
    return data;
  }
  function handleError(error, quiet = false) {
    if (error.code === 'unauthorized') resetAuthentication(error.message);
    else { connection('Нет обновления'); if (!quiet) notice(error.message); }
  }
  async function loadMe() {
    const data = await api('me'); state.me = data; state.botUsername = data.bot_username || '';
    const initial = (data.user.first_name || 'S').slice(0, 1).toUpperCase();
    $('#avatar').textContent = initial; $('#profile-avatar').textContent = initial;
    $('#profile-name').textContent = data.user.first_name; $('#profile-username').textContent = data.user.username ? '@' + data.user.username : 'Покупатель Session';
    $('#profile-id').textContent = data.user.id; $('#header-balance').textContent = rub(data.balance);
    $('#profile-balance').textContent = rub(data.balance); $('#profile-usdt').textContent = number(data.balance_usdt) + ' USDT';
    $('#sidebar-version').textContent = 'v' + data.version;
  }
  function renderCatalog() {
    const total = state.categories.reduce((sum, c) => sum + Number(c.count), 0);
    $('#total-count').textContent = total; $('#sidebar-count').textContent = total;
    $('#categories').innerHTML = [{ slug: '', name: 'Все аккаунты', count: total }, ...state.categories].map(c => `<button class="category ${state.category === c.slug ? 'active' : ''}" data-category="${esc(c.slug)}">${esc(c.name)}<span class="category-count">${c.count}</span></button>`).join('');
    $('#catalog-grid').innerHTML = state.items.map(item => `<article class="account-card"><div class="card-head"><span class="flag" aria-hidden="true">${flag(item.category)}</span><span class="stock-tag"><span></span>В наличии</span></div><h3>${esc(item.name)}</h3><div class="card-phone">${esc(item.phone)}</div><div class="card-details"><span class="detail-tag">Telegram</span><span class="detail-tag">ID ${item.id}</span></div><div class="card-bottom"><div>${Number(item.discount) > 0 ? `<span class="old-price">${rub(item.original_price)}</span>` : ''}<span class="card-price">${number(item.price)}<small>₽</small></span></div><button class="buy-button" data-buy="${item.id}" aria-label="Купить ${esc(item.name)} за ${rub(item.price)}">${icon('arrow')}</button></div></article>`).join('');
    $('#catalog-empty').hidden = state.items.length > 0;
  }
  async function loadCatalog(append = false) {
    const requestId = ++state.catalogRequest;
    const page = append ? state.page + 1 : 0;
    const query = new URLSearchParams({ category: state.category, q: $('#search').value.trim(), sort: $('#sort').value, page });
    const data = await api('catalog?' + query);
    if (requestId !== state.catalogRequest) return;
    state.categories = data.categories; state.items = append ? [...state.items, ...data.items] : data.items; state.page = page;
    renderCatalog(); $('#load-more').hidden = !data.has_more;
  }
  function renderOrders() {
    $('#orders-list').innerHTML = state.orders.map(order => `<button class="order-row" data-order="${order.id}"><span class="flag" aria-hidden="true">${icon('bag')}</span><span class="order-row-main"><h3>${esc(order.name)}</h3><p>Заказ #${order.id} · ${esc(order.date)}</p></span><span class="order-right">${order.paid_amount != null ? number(order.paid_amount) + ' ' + (order.currency === 'RUB' ? '₽' : esc(order.currency)) : '—'}<span class="order-status">${esc(order.status_label)}</span></span></button>`).join('');
    $('#orders-empty').hidden = state.orders.length > 0;
  }
  async function loadOrders(append = false) {
    const page = append ? state.orderPage + 1 : 0;
    const data = await api('orders?page=' + page); state.orders = append ? [...state.orders, ...data.items] : data.items; state.orderPage = page;
    renderOrders(); $('#more-orders').hidden = !data.has_more;
  }
  async function switchTab(tab) {
    if (!['catalog', 'orders', 'profile'].includes(tab)) return;
    if (!state.ready) { toast('Сначала открой приложение из Telegram-бота.'); return; }
    state.tab = tab;
    for (const el of document.querySelectorAll('.page')) el.hidden = el.id !== tab + '-page';
    for (const el of document.querySelectorAll('[data-tab]')) el.classList.toggle('active', el.dataset.tab === tab);
    $('#breadcrumb').textContent = { catalog: 'Каталог', orders: 'Покупки', profile: 'Профиль' }[tab];
    tg?.HapticFeedback?.selectionChanged();
    try { if (tab === 'orders') await loadOrders(); else if (tab === 'profile') await loadMe(); } catch (error) { handleError(error); }
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  function openBot(orderId) {
    if (state.botUsername && /^[a-zA-Z0-9_]+$/.test(state.botUsername)) {
      const url = 'https://t.me/' + state.botUsername + (orderId ? '?start=order_' + orderId : '');
      if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank', 'noopener');
    } else if (tg?.initData) tg.close(); else toast('Открой приложение из Telegram-бота.');
  }
  function purchaseDialog(id) {
    const item = state.items.find(i => i.id === id); if (!item) return;
    state.selected = item; state.busy = false;
    $('#dialog-kicker').textContent = 'ТВОЙ НОВЫЙ АККАУНТ';
    $('#dialog-content').innerHTML = `<div class="dialog-flag">${flag(item.category)}</div><h2 id="dialog-title">${esc(item.name)}</h2><p>${esc(item.phone)} · Аккаунт #${item.id}</p><div class="profile-info"><span>Стоимость</span><strong>${rub(item.price)}</strong></div><div class="profile-info"><span>Твой баланс</span><strong>${rub(state.me?.balance)}</strong></div><p>После оплаты аккаунт появится в покупках — и здесь, и в боте. Коды входа доступны в Telegram-боте.</p><p id="checkout-error" class="dialog-error" role="alert" hidden></p><button id="confirm-purchase" class="primary-button">Купить за ${rub(item.price)} ${icon('arrow')}</button>`;
    $('#purchase-dialog').showModal();
  }
  async function confirmPurchase() {
    if (state.busy || !state.selected) return;
    state.busy = true; const selected = state.selected;
    const btn = $('#confirm-purchase'); btn.disabled = true; btn.textContent = 'Оформляем покупку…';
    try {
      const result = await api('purchase', { method: 'POST', body: JSON.stringify({ account_id: selected.id, price: selected.price }) });
      tg?.HapticFeedback?.notificationOccurred('success');
      $('#dialog-content').innerHTML = `<div class="success-icon">${icon('check')}</div><h2 id="dialog-title">Аккаунт твой!</h2><p>Заказ #${result.id} оплачен и выдан.<br>Списано ${rub(result.paid_amount)}. Остаток ${rub(result.balance)}.</p><button class="primary-button" data-bot-order="${result.id}">Открыть заказ в боте ↗</button><button class="secondary-button" id="show-my-orders">Мои покупки</button>`;
      await synchronize(true);
    } catch (error) {
      if (error.code === 'unauthorized') { resetAuthentication(error.message); return; }
      if ($('#checkout-error')) { $('#checkout-error').hidden = false; $('#checkout-error').textContent = error.message; }
      if ($('#confirm-purchase')) { $('#confirm-purchase').disabled = false; $('#confirm-purchase').textContent = 'Повторить покупку'; }
      if (['sold', 'price_changed'].includes(error.code)) { if ($('#confirm-purchase')) $('#confirm-purchase').disabled = true; loadCatalog().catch(() => {}); }
      tg?.HapticFeedback?.notificationOccurred('error');
    } finally { state.busy = false; }
  }
  async function showOrder(id) {
    try {
      const order = await api('orders/' + id);
      $('#dialog-kicker').textContent = 'МОЯ ПОКУПКА';
      $('#dialog-content').innerHTML = `<h2 id="dialog-title">Заказ #${order.id}</h2><p>${esc(order.status_label)} · ${esc(order.date)}</p><div class="profile-info"><span>Номер</span><strong class="secret-value">${esc(order.number || '—')}</strong></div><div class="profile-info"><span>Пароль 2FA</span><strong class="secret-value" id="order-password">••••••</strong></div><button class="secondary-button" id="show-password">Показать пароль</button><p>Получи код входа, заверши покупку или обратись в поддержку в Telegram-боте.</p><button class="primary-button" data-bot-order="${order.id}">Продолжить в боте ↗</button>`;
      if (order.status === 'refunded') { $('#order-password').textContent = 'Доступ закрыт'; $('#show-password').hidden = true; }
      $('#show-password').addEventListener('click', () => { $('#order-password').textContent = order.password || 'Не установлен'; $('#show-password').hidden = true; }, { once: true });
      $('#purchase-dialog').showModal();
    } catch (error) { handleError(error); }
  }
  async function synchronize(quiet = false) {
    if (!state.ready || document.hidden) return;
    try {
      await Promise.all([loadMe(), state.tab === 'catalog' ? loadCatalog() : state.tab === 'orders' ? loadOrders() : Promise.resolve()]);
      connection('Обновлено сейчас'); if (!quiet) notice();
    } catch (error) { handleError(error, quiet); }
  }
  async function initialize() {
    try {
      tg?.ready(); tg?.expand(); tg?.setHeaderColor('#f5f7f8'); tg?.setBackgroundColor('#f5f7f8');
      await loadMe(); state.ready = true; $('#login-panel').hidden = true; notice();
      for (const el of document.querySelectorAll('.page')) el.hidden = el.id !== state.tab + '-page';
      await loadCatalog(); connection('Обновлено сейчас');
    } catch (error) { resetAuthentication(error.message); }
  }
  document.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    if (button.hasAttribute('data-tab')) switchTab(button.dataset.tab);
    if (button.hasAttribute('data-category') && state.ready) { state.category = button.dataset.category; loadCatalog().catch(handleError); }
    if (button.hasAttribute('data-buy')) purchaseDialog(Number(button.dataset.buy));
    if (button.hasAttribute('data-order')) showOrder(Number(button.dataset.order));
    if (button.hasAttribute('data-bot-link')) openBot();
    if (button.hasAttribute('data-bot-order')) openBot(Number(button.dataset.botOrder));
    if (button.id === 'confirm-purchase') confirmPurchase();
    if (button.id === 'show-my-orders') { $('#purchase-dialog').close(); switchTab('orders'); }
  });
  $('#close-dialog').addEventListener('click', () => { if (!state.busy) $('#purchase-dialog').close(); });
  $('#purchase-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
  $('#purchase-dialog').addEventListener('close', () => { state.selected = null; $('#dialog-content').replaceChildren(); });
  $('#search').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { if (state.ready) loadCatalog().catch(handleError); }, 250); });
  $('#sort').addEventListener('change', () => { if (state.ready) loadCatalog().catch(handleError); });
  $('#refresh').addEventListener('click', () => synchronize()); $('#refresh-orders').addEventListener('click', () => synchronize());
  $('#load-more').addEventListener('click', async () => { $('#load-more').disabled = true; try { await loadCatalog(true); } catch (e) { handleError(e); } finally { $('#load-more').disabled = false; } });
  $('#more-orders').addEventListener('click', async () => { $('#more-orders').disabled = true; try { await loadOrders(true); } catch (e) { handleError(e); } finally { $('#more-orders').disabled = false; } });
  $('#retry-login').addEventListener('click', initialize);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) synchronize(true); });
  window.addEventListener('online', () => synchronize()); window.addEventListener('offline', () => { connection('Нет соединения'); notice('Нет соединения. Данные обновятся после подключения к интернету.'); });
  setInterval(() => { if (!state.busy) synchronize(true); }, 15000);
  initialize();
})();
