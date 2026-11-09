/* Shared links never contain Telegram initData, fragments or user credentials. */
(() => {
 'use strict';
 function link(username, origin=location.origin){
  return typeof username==='string'&&/^[A-Za-z0-9_]{5,32}$/.test(username)?'https://t.me/'+username+'?start=miniapp':origin;
 }
 async function copy(value,input){
  try{if(!navigator.clipboard?.writeText)throw Error('clipboard');await navigator.clipboard.writeText(value);return true;}
  catch(_){input?.focus();input?.select();return false;}
 }
 function share(value){
  const url='https://t.me/share/url?'+new URLSearchParams({url:value,text:window.SbandT('SBAND ACCS — аккаунты и цифровые товары')});
  const tg=window.Telegram?.WebApp;
  if(tg?.openTelegramLink)tg.openTelegramLink(url);else window.open(url,'_blank','noopener,noreferrer');
 }
 window.SbandSharing={link,copy,share};
})();
