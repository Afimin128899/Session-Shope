'use strict';
(async () => {
  const status = document.getElementById('status');
  const tg = window.Telegram?.WebApp;
  tg?.ready(); tg?.expand();
  tg?.setHeaderColor('#101010'); tg?.setBackgroundColor('#101010');
  if (!tg?.initData) {
    status.textContent = 'Mini App доступен только администраторам. Откройте его кнопкой в боте.';
    return;
  }
  try {
    const response = await fetch('/api/storefront-preview', {headers:{Authorization:'tma ' + tg.initData},cache:'no-store'});
    if (!response.ok) {
      status.textContent = response.status === 403 ? 'Доступ к Mini App есть только у администраторов.' : 'Не удалось проверить доступ. Закройте Mini App и откройте снова.';
      return;
    }
    const html = await response.text();
    // Only the authenticated server endpoint supplies this preserved app shell.
    document.open(); document.write(html); document.close();
  } catch (_) {
    status.textContent = 'Не удалось проверить доступ. Попробуйте позже.';
  }
})();
