'use strict';
// One authenticated transport for the storefront and administration. Mutations are never retried.
let sbandLocaleRevision=0;
window.SbandRequest = async function(path, options = {}) {
  const languageChange=path==='preferences/language'&&options.method==='POST';
  if(languageChange)sbandLocaleRevision++;
  const localeRevision=sbandLocaleRevision;
  const failure = (message, code) => Object.assign(new Error(message), {code});
  const raw = window.Telegram?.WebApp?.initData;
  if (!raw) throw failure(SbandT("Открой приложение заново через Telegram-бота."), 'unauthorized');
  const {zip = false, ...requestOptions} = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), zip ? 60000 : 20000);
  try {
    const response = await fetch('/api/' + path, {
      ...requestOptions, cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
      headers: {Authorization: 'tma ' + raw, ...(options.body ? {'Content-Type': zip ? 'application/zip' : 'application/json'} : {})}
    });
    const locale=response.headers.get('Content-Language');
    if(!languageChange&&localeRevision===sbandLocaleRevision&&(locale==='ru'||locale==='en'))window.SbandI18n?.setLanguage(locale);
    if (response.status === 401) throw failure(SbandT("Срок входа истёк. Открой приложение заново через Telegram."), 'unauthorized');
    if (response.status === 403) throw failure(SbandT("Действие недоступно для этого аккаунта."), 'forbidden');
    let data;
    try { data = await response.json(); }
    catch (_) { throw failure(SbandT("Сервер вернул неполный ответ. Проверь результат операции перед повтором."), 'invalid_response'); }
    if (!response.ok) {
      const fallback = response.status === 429 ? SbandT("Слишком много запросов. Подожди минуту.") : SbandT("Сервис временно недоступен. Попробуй позже.");
      throw Object.assign(failure(typeof data?.error === 'string' ? data.error : fallback, data?.code || 'unavailable'),{details:data});
    }
    if(languageChange){sbandLocaleRevision++;window.SbandI18n?.setLanguage(data.language);}
    return data;
  } catch (e) {
    if (typeof e.code === 'string') throw e;
    const mutation = options.method && options.method !== 'GET';
    throw failure((e.name === 'AbortError' ? SbandT("Сервер не ответил вовремя.") : SbandT("Нет соединения с сервером.")) +
      (mutation ? SbandT(" Проверь результат операции перед повтором.") : SbandT(" Проверь интернет и обнови раздел.")), 'connection');
  } finally { clearTimeout(timer); }
};
