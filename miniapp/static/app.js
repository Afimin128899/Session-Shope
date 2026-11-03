'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const tg = window.Telegram?.WebApp;
  const state = { tab: 'catalog', wholesale:{minimum:'500',percent:'15'}, ready: false, me: null, items: [], page: 0, category: '', orderPage: 0, orders: [], busy: false, revision: 0, invoice: null, refreshing: false, dialogRevision: 0 };
  const labels = { catalog: 'Каталог', favorites: 'Избранное', cart: 'Корзина', orders: 'Покупки', profile: 'Профиль' };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const num = v => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(v || 0));
  const rub = v => num(v) + ' ₽';
  const spamLabel = check => check?.running ? 'Проверяется…' : (check?.label || 'Не проверен');
  const spamTime = check => check?.checked_at ? new Date(check.checked_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})+' МСК' : 'Пока не проверялся';
  const flags = { us: '🇺🇸', ru: '🇷🇺', kz: '🇰🇿', ua: '🇺🇦', gb: '🇬🇧', de: '🇩🇪', fr: '🇫🇷', in: '🇮🇳', tr: '🇹🇷', uz: '🇺🇿', nl: '🇳🇱', ca: '🇨🇦', pl: '🇵🇱', br: '🇧🇷' };
  let toastTimer, searchTimer;
  function toast(text) { $('#toast').textContent = text; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 4500); }
  function notice(text = '') { $('#notice').textContent = text; $('#notice').hidden = !text; }
  function reset(text) {
    if($('#demo-mode-notice'))$('#demo-mode-notice').hidden=true;
    document.querySelectorAll('[data-demo]').forEach(button=>button.hidden=true);
    window.SBAND_USER=null; document.dispatchEvent(new Event('sband-logout')); state.ready = false; state.me = null; state.items = []; state.orders = []; state.invoice = null; state.revision++;
    $('#header-balance').textContent = '— ₽'; $('#profile-balance').textContent = '— ₽'; $('#catalog-grid').replaceChildren(); $('#orders-list').replaceChildren();
    document.querySelectorAll('.page').forEach(el => { el.hidden = true; }); $('#login-panel').hidden = false;
    $('#purchase-dialog').close(); $('#dialog-content').replaceChildren(); $('#sync-state').textContent = 'Нужен вход'; notice(text);
  }
  const api = (path, options = {}) => window.SbandRequest(path, options);
  const post = (path, body, method = 'POST') => api(path, { method, body: JSON.stringify(body) });
  function error(e) { if (e.code === 'unauthorized') reset(e.message); else notice(e.message || 'Проверь соединение и попробуй ещё раз.'); }
  function openBot(id) {
    const username = state.me?.bot_username;
    if (!username || !/^[a-zA-Z0-9_]+$/.test(username)) { toast('Открой Telegram-бота, из которого запущен магазин.'); return; }
    const url = 'https://t.me/' + username + (id ? '?start=order_' + id : '');
    if (tg?.openTelegramLink) tg.openTelegramLink(url); else window.open(url, '_blank', 'noopener,noreferrer');
  }
  async function loadMe() {
    const data = await api('me'); state.me = data; window.SBAND_USER=data; document.dispatchEvent(new CustomEvent('sband-identity',{detail:data}));
    document.querySelectorAll('[data-demo]').forEach(button=>button.hidden=!data.is_admin);
    if($('#demo-mode-notice'))$('#demo-mode-notice').hidden=!data.test_mode_active;
    const initial = (data.user.first_name || 'S').slice(0, 1).toUpperCase();
    $('#avatar').textContent = initial; $('#profile-avatar').textContent = initial;
    $('#profile-name').textContent = data.user.first_name || 'Покупатель'; $('#profile-username').textContent = data.user.username ? '@' + data.user.username : 'Покупатель Sband ACCS';
    $('#profile-id').textContent = data.user.id; $('#header-balance').textContent = rub(data.balance); $('#profile-balance').textContent = rub(data.balance);
    $('#profile-usdt').textContent = num(data.balance_usdt) + ' USDT'; $('#version').textContent = 'v' + data.version;
  }
  function render() {
    $('#catalog-grid').innerHTML = state.items.map(item => `<article class="account-card"><div class="card-head"><span class="flag" aria-hidden="true">${flags[item.category] || '✳'}</span><div class="card-head-right">${item.characteristics?.is_premium ? '<span class="premium-badge">Premium</span>' : ''}<button class="heart ${item.favorite ? 'selected' : ''}" data-favorite="${item.id}" aria-label="${item.favorite ? 'Убрать из избранного' : 'В избранное'}" aria-pressed="${item.favorite}">${item.favorite ? '♥' : '♡'}</button></div></div><h3>${esc(item.name)}</h3><span class="stock-tag ${item.available ? '' : 'unavailable'}">${item.available ? 'В наличии' : 'Недоступен'}</span><button class="feature-link" data-features="${item.id}">Характеристики ${item.characteristics?.warranty_hours ? '· '+item.characteristics.warranty_hours+' ч гарантии' : '↗'}</button><div class="card-phone">${esc(item.phone)}</div><div class="spam-line ${item.characteristics?.spam_check?.status === 'limited' ? 'spam-limited' : ''}" title="${esc(spamTime(item.characteristics?.spam_check))}">Спамблок: ${esc(spamLabel(item.characteristics?.spam_check))}</div><div class="ids"><div><span>Товар</span><b>${esc(item.product_id)}</b></div><div><span>Telegram ID</span><b>${esc(item.telegram_user_id || 'Не сохранён')}</b></div></div><div class="card-bottom"><div>${Number(item.discount)>0 ? `<span class="old-price"><s>${rub(item.original_price)}</s><span class="discount-badge">−${num(item.discount)}%</span></span>` : ''}<span class="card-price">${num(item.price)}<small>₽</small></span></div><button class="buy-button ${item.in_cart ? 'added' : ''}" data-add="${item.id}" ${!item.available ? 'disabled' : ''} aria-label="${item.in_cart ? 'Обновить резерв' : 'В корзину'} ${esc(item.name)}">${item.in_cart ? '✓' : '+'}</button></div>${item.in_cart ? `<div class="reserve" data-until="${esc(item.reserved_until || '')}"></div><button class="remove-button" data-remove="${item.id}">Убрать из корзины</button>` : ''}</article>`).join('');
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
    if (tab === 'catalog') { query.set('category', state.category); query.set('q', $('#search').value); query.set('sort', $('#sort').value); query.set('min_price', $('#min-price').value); query.set('max_price', $('#max-price').value); query.set('premium',$('#premium-filter').value);query.set('min_age',$('#age-filter').value); }
    const data = await api((tab === 'catalog' ? 'catalog' : tab) + '?' + query);
    if (rev !== state.revision || state.tab !== tab || !state.ready) return;
    state.page = page; state.items = append ? [...state.items, ...data.items] : data.items;
    $('#total-count').textContent = tab === 'catalog' ? data.categories.reduce((n, c) => n + Number(c.count), 0) : state.items.length;
    $('#categories').innerHTML = [{ slug: '', name: 'Все аккаунты', count: data.categories.reduce((n, c) => n + Number(c.count), 0) }, ...data.categories].map(c => `<button class="category ${c.slug === state.category ? 'active' : ''}" data-category="${esc(c.slug)}">${esc(c.name)}<small>${c.count}</small></button>`).join('');
    $('#load-more').hidden = !data.has_more; render();
  }
  async function loadOrders(append = false) {
    const revision=state.orderRevision=(state.orderRevision || 0)+1;
    const page = append ? state.orderPage + 1 : 0, data = await api('orders?page=' + page+'&q='+encodeURIComponent($('#order-search').value));
    if (!state.ready || revision!==state.orderRevision) return;
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
  function modal(html) { state.dialogRevision++; $('#dialog-content').innerHTML = html; if (!$('#purchase-dialog').open) $('#purchase-dialog').showModal(); }
  function dialogError(e) { if (e.code === 'unauthorized') { reset(e.message); return; } const el = $('#dialog-error'); if (el) { el.textContent = e.message; el.hidden = false; } else error(e); }
  async function checkout() {
    if (!state.items.length || state.busy) return;
    const items = state.items.map(i => ({ account_id: i.id, price: i.price, warranty_hours:i.characteristics?.warranty_hours ?? null, spam_status:i.characteristics?.spam_check?.status || 'not_checked' }));
    let promo = null;
    const base = items.reduce((n,i)=>n+Math.round(Number(i.price)*100),0)/100;
    const bulk = base>=Number(state.wholesale.minimum) ? Number(state.wholesale.percent) : 0;
    const sum = rate => items.reduce((n,i) => n + Math.round(Math.round(Math.round(Number(i.price)*100)*(10000-Math.round(bulk*100))/10000)*(10000-Math.round(Number(rate)*100))/10000),0)/100;
    const total = sum(0);
    modal(`<h2 id="dialog-title">Подтвердить покупку</h2><p>${items.length} аккаунт(ов). После оплаты они появятся в покупках и Telegram-боте.</p><p>${state.items.map(i=>esc(i.product_id)+': гарантия '+(i.characteristics?.warranty_hours == null ? 'не указана' : i.characteristics.warranty_hours+' ч')+'; спамблок: '+esc(spamLabel(i.characteristics?.spam_check))).join('<br>')}</p><p>Гарантия на проблемы со входом в пределах срока. Решение по обращению принимает поддержка после проверки.</p><div class="info"><span>К оплате</span><b id="quoted-total">${rub(total)}</b></div><div class="info"><span>Баланс</span><b>${rub(state.me.balance)}</b></div><p>Оптовая скидка: ${bulk}%. Порог ${rub(state.wholesale.minimum)} до применения промокода.</p><label for="coupon-code">Промокод (необязательно)</label><input id="coupon-code" maxlength="64" placeholder="Например, SBAND10"><button id="preview-coupon" class="secondary-button">Проверить промокод</button><p id="coupon-result" aria-live="polite"></p><p id="dialog-error" class="dialog-error" role="alert" hidden></p><button id="confirm-purchase" class="primary-button">Оплатить ${rub(total)} <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
    const confirmButton = $('#confirm-purchase');
    $('#preview-coupon').onclick = async () => {
      if (state.busy) return;
      confirmButton.disabled = true; $('#preview-coupon').disabled = true;
      promo = null; $('#dialog-error').hidden = true;
      const typed = $('#coupon-code').value;
      try {
        const result = await post('promo/preview',{code:typed});
        if (!confirmButton.isConnected || $('#coupon-code').value !== typed) return;
        if (result.kind === 'balance') {
          $('#coupon-result').textContent = 'Этот код пополнит баланс на '+rub(result.value)+'. Активируй его в профиле, затем вернись к оплате.';
        } else {
          promo = result;
          $('#coupon-result').textContent = 'Дополнительная скидка '+num(result.value)+'%. Экономия '+rub(total-sum(result.value))+'. Код будет использован только после успешной покупки.';
        }
      } catch (e) { if (confirmButton.isConnected) dialogError(e); }
      finally {
        if (confirmButton.isConnected) {
          $('#quoted-total').textContent = rub(sum(promo?.value || 0));
          confirmButton.textContent = 'Оплатить '+rub(sum(promo?.value || 0));
          confirmButton.disabled = false; $('#preview-coupon').disabled = false;
        }
      }
    };
    $('#coupon-code').oninput = () => { promo = null; $('#dialog-error').hidden = true; $('#quoted-total').textContent = rub(total); confirmButton.textContent = 'Оплатить '+rub(total); $('#coupon-result').textContent = ''; };
    $('#confirm-purchase').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#confirm-purchase').disabled = true;
      try {
        const result = await post('cart/checkout', { items, expected_total:sum(promo?.value || 0).toFixed(2), ...(promo ? {promo_code:promo.code} : {}) });
        modal(`<div class="success-icon">✓</div><h2 id="dialog-title">Покупка готова!</h2><p>Заказов: ${result.order_ids.length}. Списано ${rub(result.paid_amount)}.<br>Остаток: ${rub(result.balance)}.</p><button class="primary-button" id="show-my-orders">Мои покупки <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
        $('#show-my-orders').onclick = () => { $('#purchase-dialog').close(); switchTab('orders'); };
        tg?.HapticFeedback?.notificationOccurred('success'); await loadMe(); await loadMarket();
      } catch (e) { dialogError(e); if ($('#confirm-purchase')) { $('#confirm-purchase').disabled = ['sold', 'price_changed', 'reservation_expired', 'cart_changed', 'terms_changed', 'invalid_promo'].includes(e.code); } await loadMarket().catch(() => {}); }
      finally { state.busy = false; }
    };
  }
  async function showOrder(id) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const o = await api('orders/' + id);
      if (dialogRevision !== state.dialogRevision) return;
      modal(`<h2 id="dialog-title">Заказ #${o.id}</h2><p>${esc(o.status_label)} · ${esc(o.date)}</p><div class="info"><span>ID товара</span><b>${esc(o.product_id || '—')}</b></div><div class="info"><span>Telegram ID</span><b>${esc(o.telegram_user_id || 'Не сохранён')}</b></div><div class="info"><span>Номер</span><b class="secret-value">${esc(o.number || '—')}</b></div><div class="info"><span>Пароль 2FA</span><b class="secret-value" id="order-password">${o.status === 'refunded' ? 'Доступ закрыт' : '••••••'}</b></div>${o.status !== 'refunded' ? '<button id="show-password" class="secondary-button">Показать пароль</button>' : ''}<p>Код входа, завершение покупки и поддержка доступны в Telegram-боте.</p><button class="primary-button" data-bot-order="${o.id}">Открыть в боте <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
      const warranty = o.warranty || {};
      $('#dialog-content').insertAdjacentHTML('beforeend', `<div class="info"><span>Спамблок при покупке</span><b>${esc(spamLabel(o.characteristics?.spam_check))}</b></div><p class="muted">${esc(spamTime(o.characteristics?.spam_check))}</p>`);
      $('#dialog-content').insertAdjacentHTML('beforeend', `<div class="warranty-box"><b>Гарантия: ${esc(warranty.label || 'Срок не сохранён')}</b>${warranty.until ? `<p>До ${esc(new Date(warranty.until).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}))} МСК</p>` : ''}<p>${esc(warranty.policy || '')}</p>${warranty.active ? '<button id="warranty-claim" class="secondary-button">Обратиться по гарантии</button>' : ''}</div><button id="write-review" class="secondary-button">${o.review ? 'Изменить отзыв' : 'Оставить отзыв'}</button>`);
      $('#write-review').onclick = () => reviewEditor(o);
      if ($('#warranty-claim')) $('#warranty-claim').onclick = () => warrantyEditor(o);
      if ($('#show-password')) $('#show-password').onclick = () => { $('#order-password').textContent = o.password || 'Не установлен'; $('#show-password').hidden = true; };
    } catch (e) { error(e); }
  }
  async function features(id) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const item=await api('products/'+id),c=item.characteristics || {};
      if (dialogRevision !== state.dialogRevision) return;
      modal(`<div class="product-cover">${flags[item.category] || '✳'}<span>TELEGRAM ACCOUNT</span></div><h2 id="dialog-title">${esc(item.name)}</h2><p>${esc(item.product_id)} · Telegram ID ${esc(item.telegram_user_id || 'Не сохранён')}</p><div class="info"><span>Регистрация</span><b>${esc(c.registration_date || 'Не указана')}</b></div><div class="info"><span>Premium</span><b>${c.is_premium == null ? 'Не проверено' : c.is_premium ? 'Да' : 'Нет'}</b></div><div class="info"><span>2FA</span><b>${esc(c.two_fa || 'Не указано')}</b></div><div class="info"><span>Спамблок</span><b>${esc(spamLabel(c.spam_check))}</b></div><p class="muted">${esc(spamTime(c.spam_check))}. Источник: @SpamBot. Состояние может измениться после проверки.</p><div class="info"><span>Гарантия</span><b>${c.warranty_hours == null ? 'Не указана' : c.warranty_hours+' ч'}</b></div><p>${esc(c.note)}</p><p>После оплаты данные появятся в покупках. Код входа выдаёт бот. После входа смените пароль и привяжите свою почту. Premium указан на момент проверки и может измениться.</p><button id="product-add" class="primary-button">В корзину · ${rub(item.price)}</button><button id="share-product" class="secondary-button">Поделиться товаром</button>`);
      $('#product-add').onclick=async()=>{try{await post('cart',{account_id:id});$('#purchase-dialog').close();toast('Добавлено в корзину');await loadMarket();}catch(e){error(e);}};
      $('#share-product').onclick=()=>{
        const url='https://t.me/'+state.me.bot_username+'?start=product_'+id;
        const share='https://t.me/share/url?url='+encodeURIComponent(url)+'&text='+encodeURIComponent(item.name+' · '+rub(item.price));
        if(tg?.openTelegramLink) tg.openTelegramLink(share);else window.open(share,'_blank','noopener,noreferrer');
      };
    }catch(e){error(e);}
  }
  function knowledge() {
    modal(`<h2 id="dialog-title">Помощь и инструкции</h2><input id="knowledge-search" type="search" placeholder="Найти ответ" aria-label="Поиск инструкции"><div id="knowledge-results"></div><p>${esc(state.support?.support_hours)}. ${esc(state.support?.response_time)}</p><button class="primary-button" data-bot>Написать поддержке / отправить скриншот</button>`);
    const entries=[['Как купить?','Добавьте аккаунты в корзину. Резерв длится 5 минут. Пополните баланс и подтвердите сумму.'],['Как войти?','Откройте покупку, введите номер в Telegram. Код получите в боте. Если указан пароль 2FA, используйте его, затем смените пароль и привяжите почту.'],['Гарантия и замена','Срок указан в заказе. Отправьте гарантийную заявку до его окончания. Поддержка проверит проблему и решит вопрос возврата или замены.'],['Как отправить скриншот?','В боте откройте обращение по заказу, нажмите Ответить и отправьте фото. Не отправляйте пароли и коды входа.'],['Оптовая скидка','Применяется автоматически от '+rub(state.wholesale.minimum)+': '+state.wholesale.percent+'%. Промокод применяется после неё.'],['Оплата не появилась','Проверка идёт автоматически. Сохраните номер счёта, проверьте статус в платёжном сервисе. При задержке обратитесь в поддержку.']];
    const render=()=>{const q=$('#knowledge-search').value.toLowerCase();$('#knowledge-results').innerHTML=entries.filter(e=>e.join(' ').toLowerCase().includes(q)).map(e=>`<details class="help-article"><summary>${esc(e[0])}</summary><p>${esc(e[1])}</p></details>`).join('') || '<p>Ответ не найден. Напишите поддержке.</p>';};
    $('#knowledge-search').oninput=render;render();
  }
  function reviewEditor(order) {
    modal(`<h2 id="dialog-title">Отзыв о покупке</h2><p>Публикуется без имени и Telegram ID. Не указывай номер, пароль или коды входа. Один отзыв на заказ, его можно изменить.</p><label for="review-rating">Оценка</label><select id="review-rating">${[5,4,3,2,1].map(r=>`<option value="${r}" ${Number(order.review?.rating) === r ? 'selected' : ''}>${r} из 5</option>`).join('')}</select><label for="review-body">Отзыв</label><textarea id="review-body" maxlength="500" rows="4">${esc(order.review?.body || '')}</textarea><p id="dialog-error" class="dialog-error" hidden></p><button id="save-review" class="primary-button">Опубликовать отзыв</button>`);
    $('#save-review').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#save-review').disabled = true;
      try { await post('reviews',{purchase_id:order.id,rating:Number($('#review-rating').value),body:$('#review-body').value}); $('#purchase-dialog').close(); toast('Отзыв опубликован'); }
      catch(e) { dialogError(e); if($('#save-review')) $('#save-review').disabled = false; }
      finally { state.busy = false; }
    };
  }
  function warrantyEditor(order) {
    modal(`<h2 id="dialog-title">Гарантийное обращение</h2><p>Опиши проблему со входом. Не отправляй пароль, код или сессию. Срок проверяется при отправке; обращение сохраняется в поддержке бота.</p><label for="claim-body">Что произошло?</label><textarea id="claim-body" maxlength="500" rows="4"></textarea><p id="dialog-error" class="dialog-error" hidden></p><button id="send-claim" class="primary-button">Отправить обращение</button>`);
    $('#send-claim').onclick = async () => {
      if (state.busy) return; state.busy = true; $('#send-claim').disabled = true;
      try { const result = await post('orders/'+order.id+'/warranty-claim',{body:$('#claim-body').value}); modal(`<h2 id="dialog-title">Обращение #${result.ticket_id}</h2><p>Сохранено. Поддержка ответит в Telegram-боте.</p><button class="primary-button" data-bot-order="${order.id}">Открыть в боте</button>`); }
      catch(e) { dialogError(e); if($('#send-claim')) $('#send-claim').disabled = false; }
      finally { state.busy = false; }
    };
  }
  async function showReviews(page = 0) {
    const dialogRevision = ++state.dialogRevision;
    try {
      const data = await api('reviews?page='+page);
      if (dialogRevision !== state.dialogRevision) return;
      modal(`<h2 id="dialog-title">Отзывы покупателей</h2><p>Средняя оценка: ${data.average == null ? '—' : num(data.average)} / 5 · Отзывов: ${data.count}</p>${data.items.map(r=>`<article class="review"><b>${Number(r.rating)} / 5 · Покупатель</b><p>${esc(r.body)}</p><small>Подтверждённая покупка</small></article>`).join('') || '<p>Отзывов пока нет. Оставить свой можно в деталях покупки.</p>'}${page ? '<button id="previous-reviews" class="secondary-button">Предыдущие</button>' : ''}${data.has_more ? '<button id="next-reviews" class="secondary-button">Следующие</button>' : ''}`);
      if($('#previous-reviews')) $('#previous-reviews').onclick = () => showReviews(page-1);
      if($('#next-reviews')) $('#next-reviews').onclick = () => showReviews(page+1);
    } catch(e) { error(e); }
  }
  function balancePromo() {
    if(!state.ready) return;
    modal('<h2 id="dialog-title">Промокод на баланс</h2><label for="balance-code">Промокод</label><input id="balance-code" maxlength="64"><p id="balance-preview"></p><p id="dialog-error" class="dialog-error" hidden></p><button id="check-balance-code" class="secondary-button">Проверить</button><button id="redeem-balance-code" class="primary-button" hidden>Активировать</button>');
    let checked = null;
    $('#balance-code').oninput = () => { checked = null; $('#redeem-balance-code').hidden = true; $('#balance-preview').textContent = ''; };
    $('#check-balance-code').onclick = async () => {
      const btn = $('#check-balance-code'); btn.disabled = true; checked = null; $('#redeem-balance-code').hidden = true; $('#dialog-error').hidden = true;
      const typed = $('#balance-code').value;
      try { const r = await post('promo/preview',{code:typed}); if (!btn.isConnected || $('#balance-code').value !== typed) return; checked = r; $('#balance-preview').textContent = r.kind === 'balance' ? 'На баланс будет зачислено '+rub(r.value) : 'Скидка '+num(r.value)+'%. Применяется в окне оплаты корзины.'; $('#redeem-balance-code').hidden = r.kind !== 'balance'; }
      catch(e) { dialogError(e); } finally { btn.disabled = false; }
    };
    $('#redeem-balance-code').onclick = async () => {
      if(!checked || state.busy) return; state.busy = true; $('#redeem-balance-code').disabled = true;
      try { const r = await post('promo/redeem',{code:checked.code}); $('#purchase-dialog').close(); await loadMe(); toast('На баланс зачислено '+rub(r.credited)); }
      catch(e) { dialogError(e); if($('#redeem-balance-code')) $('#redeem-balance-code').disabled = false; } finally { state.busy = false; }
    };
  }
  async function wheel() {
    if(!state.ready || state.busy) return;
    try {
      const d=await api('rewards');
      modal(`<h2 id="dialog-title">Колесо удачи</h2><p>Случайный бонус от 1 до 10 ₽ на баланс. Шанс каждой целой суммы — 10%.</p><p>Пополнения в сумме от 50 ₽ за последние 72 часа. Получение раз в 3 дня. Промокоды, подарки и возвращённые Stars не учитываются.</p><p>Подходящие пополнения: ${rub(d.paid)}.</p>${d.next_at ? `<p>Следующий интервал: ${esc(new Date(d.next_at).toLocaleString('ru-RU',{timeZone:'Europe/Moscow'}))} МСК</p>` : ''}<p id="dialog-error" hidden></p><button id="claim-wheel" class="primary-button" ${d.eligible?'':'disabled'}>Крутить колесо</button>`);
      $('#claim-wheel').onclick=async()=>{
        if(state.busy) return;state.busy=true;$('#claim-wheel').disabled=true;
        try {const r=await post('rewards/claim',{});modal(`<h2 id="dialog-title">Ваш бонус: ${rub(r.amount)}</h2><p>Уже зачислен на баланс. Следующее получение — через 3 дня при выполнении условия пополнения.</p>`);await loadMe();}
        catch(e){dialogError(e);}finally{state.busy=false;}
      };
    }catch(e){error(e);}
  }
  async function topup() {
    const dialogRevision = ++state.dialogRevision;
    if (!state.ready || state.busy) return;
    if (state.invoice) { showInvoice(); return; }
    try {
      const data = await api('payment-methods'), methods = data.items.filter(m => m.enabled);
      if (dialogRevision !== state.dialogRevision) return;
      if (!methods.length) { modal('<h2 id="dialog-title">Пополнение баланса</h2><p>Платёжные сервисы пока не настроены. Обратись к администратору через Telegram-бота.</p><button class="primary-button" data-bot>Открыть бота <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>'); return; }
      modal(`<h2 id="dialog-title">Пополнить баланс</h2><p>Баланс обновится после подтверждения оплаты.</p><label for="topup-method">Способ оплаты</label><select id="topup-method">${methods.map(m => `<option value="${esc(m.id)}">${esc(m.name)}</option>`).join('')}</select><label for="topup-amount" id="topup-amount-label">Сумма, ₽</label><input id="topup-amount" type="number" inputmode="decimal" min="10" max="1000000" step="0.01" value="500"><p id="topup-quote" class="muted" aria-live="polite"></p><p id="dialog-error" class="dialog-error" role="alert" hidden></p><button class="primary-button" id="create-invoice">Создать счёт <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></button>`);
      const amountInput = $('#topup-amount'), methodInput = $('#topup-method'), createButton = $('#create-invoice');
      const remembered = { rub: '500', stars: '100' };
      let currentUnit = null;
      const starCount = () => /^[0-9]{1,5}$/.test(amountInput.value) && Number(amountInput.value) >= 1 && Number(amountInput.value) <= 10000;
      const updateQuote = () => {
        const stars = methodInput.value === 'stars', unit = stars ? 'stars' : 'rub';
        if (currentUnit !== unit) {
          if (currentUnit) remembered[currentUnit] = amountInput.value;
          amountInput.value = remembered[unit]; currentUnit = unit;
        }
        $('#topup-amount-label').textContent = stars ? 'Количество звёзд, ⭐' : 'Сумма, ₽';
        amountInput.min = stars ? '1' : '10'; amountInput.max = stars ? '10000' : '1000000'; amountInput.step = stars ? '1' : '0.01'; amountInput.inputMode = stars ? 'numeric' : 'decimal';
        const valid = !stars || starCount();
        $('#topup-quote').textContent = stars ? (valid ? `${num(amountInput.value)} ⭐ → ${Number(amountInput.value * 120 / 100).toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ₽ на баланс. Курс: 1 ⭐ = 1,20 ₽.` : 'Введите целое число от 1 до 10 000 ⭐.') : 'Сумма пополнения указывается в рублях.';
        createButton.disabled = state.busy || !valid;
      };
      methodInput.onchange = updateQuote; amountInput.oninput = updateQuote; updateQuote();
      createButton.onclick = async () => {
        if (state.busy || (methodInput.value === 'stars' && !starCount())) return;
        const provider = methodInput.value;
        const body = provider === 'stars' ? { provider, stars: Number(amountInput.value) } : { provider, amount: amountInput.value };
        const revision = state.dialogRevision;
        state.busy = true; createButton.disabled = true; amountInput.disabled = true; methodInput.disabled = true;
        try {
          state.invoice = await post('invoices', body);
          if (revision === state.dialogRevision) showInvoice();
        } catch (e) { dialogError(e); }
        finally { state.busy = false; if (createButton.isConnected) { amountInput.disabled = false; methodInput.disabled = false; updateQuote(); } }
      };
    } catch (e) { error(e); }
  }
  function showInvoice() {
    const i = state.invoice; if (!i) return;
    let url;
    try { url = new URL(i.pay_url); } catch (_) { state.invoice = null; throw new Error('Не удалось открыть ссылку счёта. Создай новый счёт.'); }
    const stars = i.provider === 'stars';
    if (url.protocol !== 'https:' || url.username || url.password || (stars && (!['t.me', 'telegram.me'].includes(url.hostname) || !Number.isInteger(i.stars) || i.stars < 1 || i.stars > 10000 || Math.round(Number(i.amount) * 100) !== i.stars * 120))) {
      state.invoice = null; throw new Error('Счёт содержит некорректные условия оплаты. Создай новый счёт.');
    }
    const nativeStars = stars && typeof tg?.openInvoice === 'function';
    const paymentControl = nativeStars ? `<button id="pay-stars" class="primary-button">Оплатить ${num(i.stars)} ⭐</button><a id="stars-payment-link" class="payment-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer" hidden>Открыть счёт в Telegram</a>` : `<a class="payment-link" href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${stars ? `Оплатить ${num(i.stars)} ⭐ в Telegram` : 'Перейти к оплате'} <svg class="arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 18 18 6M6 6h12v12"/></svg></a>`;
    modal(`<h2 id="dialog-title">${stars ? `Счёт на ${num(i.stars)} ⭐` : `Счёт на ${rub(i.amount)}`}</h2>${stars ? `<div class="info"><span>На баланс</span><b>${rub(i.amount)}</b></div><p>Курс: 1 ⭐ = 1,20 ₽. Зачисление произойдёт после подтверждения оплаты Telegram.</p>` : '<p>Перейди к оплате. Баланс обновится автоматически после подтверждения платёжным сервисом.</p>'}${paymentControl}<p id="invoice-state" role="status">Ожидаем оплату…</p><p id="dialog-error" class="dialog-error" role="alert" hidden></p>${stars ? '<button id="verify-invoice" class="secondary-button">Проверить зачисление</button>' : ''}<p>Можно закрыть это окно: проверка продолжится на сервере.</p><button id="another-invoice" class="secondary-button">Создать другой счёт</button>`);
    if (nativeStars) {
      const button = $('#pay-stars');
      button.onclick = () => {
        if (button.disabled || state.invoice !== i) return;
        button.disabled = true;
        try {
          tg.openInvoice(url.href, async status => {
            if (state.invoice !== i) return;
            button.disabled = false;
            const label = $('#invoice-state');
            if (label) label.textContent = status === 'paid' || status === 'pending' ? 'Проверяем подтверждение оплаты Telegram…' : status === 'cancelled' ? 'Оплата отменена. Можно открыть счёт снова.' : 'Оплата не завершена. Проверь статус счёта или попробуй снова.';
            if (status === 'paid' || status === 'pending') {
              try { await checkInvoice(); await loadMe(); } catch (e) { dialogError(e); }
            }
          });
        } catch (_) {
          button.disabled = false;
          $('#stars-payment-link').hidden = false;
          $('#invoice-state').textContent = 'Не удалось открыть оплату в приложении. Воспользуйся ссылкой на счёт в Telegram.';
        }
      };
    }
    if ($('#verify-invoice')) $('#verify-invoice').onclick = async () => {
      const button = $('#verify-invoice'); button.disabled = true;
      try { await checkInvoice(); await loadMe(); } catch (e) { dialogError(e); }
      finally { if (button.isConnected && state.invoice === i) button.disabled = false; }
    };
    $('#another-invoice').onclick = () => { state.invoice = null; topup(); };
  }
  async function checkInvoice() {
    const i = state.invoice; if (!i) return;
    const data = await api('invoices/' + encodeURIComponent(i.provider) + '/' + encodeURIComponent(i.invoice_id));
    if (state.invoice !== i) return;
    if (data.status === 'credited' || data.status === 'refunded') {
      state.invoice = null; await loadMe();
      if ($('#invoice-state')) $('#invoice-state').textContent = data.status === 'credited' ? '✓ Оплата подтверждена. Баланс пополнен!' : 'Платёж возвращён. Баланс обновлён.';
      if ($('#pay-stars')) $('#pay-stars').disabled = true;
      if ($('#verify-invoice')) $('#verify-invoice').disabled = true;
      toast(data.status === 'credited' ? 'Баланс пополнен автоматически' : 'Возврат платежа подтверждён');
    } else if (data.status === 'expired') {
      state.invoice = null;
      if ($('#invoice-state')) $('#invoice-state').textContent = 'Срок счёта истёк. Создай новый счёт.';
      if ($('#pay-stars')) $('#pay-stars').disabled = true;
      if ($('#verify-invoice')) $('#verify-invoice').disabled = true;
    }
  }
  async function synchronize() {
    if (!state.ready || state.busy || state.refreshing || document.hidden || document.body.classList.contains('admin-mode')) return;
    state.refreshing = true;
    try { await Promise.all([loadMe(), state.tab === 'orders' ? (state.orderPage === 0 ? loadOrders() : null) : (state.page === 0 ? loadMarket() : null), checkInvoice()]); $('#sync-state').textContent = (state.tab === 'orders' ? state.orderPage : state.page) > 0 ? '● Баланс обновлён' : '● Обновлено сейчас'; }
    catch(e) { $('#sync-state').textContent='Нет обновления'; if(e.code==='unauthorized') reset(e.message); }
    finally { state.refreshing=false; }
  }
  async function initialize() {
    try { tg?.ready(); tg?.expand(); tg?.setHeaderColor('#101114'); tg?.setBackgroundColor('#101114'); await loadMe(); const info=await api('shop-info');state.wholesale=info.wholesale;state.support=info; state.ready = true; $('#login-panel').hidden = true; notice(); showPage(); await loadMarket(); $('#sync-state').textContent = '● Обновлено сейчас'; const start=tg?.initDataUnsafe?.start_param || new URLSearchParams(location.search).get('tgWebAppStartParam') || (new URLSearchParams(location.search).get('product') ? 'product_'+new URLSearchParams(location.search).get('product') : ''); if(/^product_[0-9]{1,10}$/.test(start)) await features(Number(start.slice(8))); }
    catch (e) { reset(e.message); }
  }
  document.addEventListener('sband-shop',()=>{if(state.ready) { showPage(); synchronize(); }});
  document.addEventListener('sband-auth-error',()=>reset('Открой приложение заново через Telegram.'));
  document.addEventListener('click', async event => {
    const button = event.target.closest('button'); if (!button || button.disabled) return;
    if(button.hasAttribute('data-demo')) { if(state.me?.is_admin){sessionStorage.setItem('sband_test_init',tg?.initData||'');location.assign('/demo'+location.hash);}return; }
    if(button.hasAttribute('data-demo-exit')) { try{await post('demo/exit',{});await loadMe();notice('Тестовый режим закрыт. Рабочие операции доступны.');}catch(e){error(e);}return; }
    if (button.dataset.tab) { switchTab(button.dataset.tab); return; }
    if (button.hasAttribute('data-bot')) openBot();
    if (button.dataset.botOrder) openBot(Number(button.dataset.botOrder));
    if (button.dataset.features) features(Number(button.dataset.features));
    if (button.hasAttribute('data-knowledge')) knowledge();
    if (button.hasAttribute('data-reviews')) showReviews();
    if (button.hasAttribute('data-balance-promo')) balancePromo();
    if (button.hasAttribute('data-wheel')) wheel();
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
  $('#purchase-dialog').addEventListener('close', () => { if (!$('#purchase-dialog').open) { state.dialogRevision++; $('#dialog-content').replaceChildren(); } });
  for (const id of ['search', 'min-price', 'max-price']) $('#' + id).addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { if (state.ready) loadMarket().catch(error); }, 300); });
  $('#sort').onchange = () => loadMarket().catch(error);
  for(const id of ['premium-filter','age-filter']) $('#'+id).onchange=()=>loadMarket().catch(error);
  $('#order-search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadOrders().catch(error),300);};
  $('#load-more').onclick = async () => { $('#load-more').disabled = true; try { await loadMarket(true); } catch (e) { error(e); } finally { $('#load-more').disabled = false; } };
  $('#more-orders').onclick = async () => { $('#more-orders').disabled = true; try { await loadOrders(true); } catch (e) { error(e); } finally { $('#more-orders').disabled = false; } };
  $('#refresh').onclick = () => loadMarket().then(() => notice()).catch(error); $('#refresh-orders').onclick = () => loadOrders().catch(error); $('#retry-login').onclick = initialize;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) synchronize(); }); window.addEventListener('online', synchronize);
  window.addEventListener('offline', () => notice('Нет соединения. Подключись к интернету, чтобы обновить данные.'));
  setInterval(countdown, 1000); setInterval(synchronize, 15000); initialize();
})();
