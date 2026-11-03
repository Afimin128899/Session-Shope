'use strict';
// One authenticated transport for the storefront and administration. Mutations are never retried.
window.SbandRequest = async function(path, options = {}) {
  const failure = (message, code) => Object.assign(new Error(message), {code});
  const raw = window.Telegram?.WebApp?.initData;
  if (!raw) throw failure('Открой приложение заново через Telegram-бота.', 'unauthorized');
  const {zip = false, ...requestOptions} = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), zip ? 60000 : 20000);
  try {
    const response = await fetch('/api/' + path, {
      ...requestOptions, cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
      headers: {Authorization: 'tma ' + raw, ...(options.body ? {'Content-Type': zip ? 'application/zip' : 'application/json'} : {})}
    });
    if (response.status === 401) throw failure('Срок входа истёк. Открой приложение заново через Telegram.', 'unauthorized');
    if (response.status === 403) throw failure('Действие недоступно для этого аккаунта.', 'forbidden');
    let data;
    try { data = await response.json(); }
    catch (_) { throw failure('Сервер вернул неполный ответ. Проверь результат операции перед повтором.', 'invalid_response'); }
    if (!response.ok) {
      const fallback = response.status === 429 ? 'Слишком много запросов. Подожди минуту.' : 'Сервис временно недоступен. Попробуй позже.';
      throw failure(typeof data?.error === 'string' ? data.error : fallback, data?.code || 'unavailable');
    }
    return data;
  } catch (e) {
    if (typeof e.code === 'string') throw e;
    const mutation = options.method && options.method !== 'GET';
    throw failure((e.name === 'AbortError' ? 'Сервер не ответил вовремя.' : 'Нет соединения с сервером.') +
      (mutation ? ' Проверь результат операции перед повтором.' : ' Проверь интернет и обнови раздел.'), 'connection');
  } finally { clearTimeout(timer); }
};
