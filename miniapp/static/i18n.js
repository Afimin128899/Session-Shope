'use strict';
// Translate source templates before inserting values. Customer content is never walked.
(() => {
 let locale='ru',catalog={};
 try{locale=localStorage.getItem('sband_language')==='en'?'en':'ru';}catch(_){}
 const shellText=[],shellAttrs=[],lastText=new WeakMap();let captured=false;const originalTitle=document.title;
 const plain=source=>{
  if(locale!=='en')return source;
  if(Object.hasOwn(catalog,source))return catalog[source];
  const trimmed=source.trim();
  return Object.hasOwn(catalog,trimmed)?source.replace(trimmed,catalog[trimmed]):source;
 };
 function sourceText(source){
  if(locale!=='en')return source;
  if(!/<[a-z!/]/i.test(source))return plain(source);
  return source.split(/(<[^>]*>)/g).map(part=>part.startsWith('<')?
   part.replace(/((?:aria-label|placeholder|title|alt)=)(["'])(.*?)\2/g,(_,key,quote,value)=>key+quote+plain(value)+quote):plain(part)).join('');
 }
 function t(source,...values){
  const translated=sourceText(String(source));
  // A callback prevents $&, $1 or braces inside customer values from being interpreted.
  return values.length?translated.replace(/\{([0-9]+)\}/g,(all,index)=>index<values.length?String(values[index]):all):translated;
 }
 function staticDOM(){
  // Only the original HTML shell is registered; dynamic reviews, credentials and
  // user-written support messages are deliberately excluded from this registry.
  if(!captured){
   const seen=new WeakSet();
   document.querySelectorAll('[data-i18n-shell]').forEach(root=>{
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
    while(walker.nextNode()){
     const node=walker.currentNode;if(seen.has(node)||node.parentElement.closest('script,style,[data-no-translate]'))continue;
     seen.add(node);shellText.push([node,node.nodeValue]);lastText.set(node,node.nodeValue);
    }
    root.querySelectorAll('[placeholder],[aria-label],[title],[alt]').forEach(node=>{
     if(node.closest('[data-no-translate]'))return;
     shellAttrs.push([node,Object.fromEntries(['placeholder','aria-label','title','alt'].filter(k=>node.hasAttribute(k)).map(k=>[k,node.getAttribute(k)]))]);
    });
   });captured=true;
  }
  for(const [node,source]of shellText){
   if(!node.isConnected||node.nodeValue!==lastText.get(node))continue;
   node.nodeValue=plain(source);lastText.set(node,node.nodeValue);
  }
  for(const [node,attrs]of shellAttrs)if(node.isConnected)for(const [key,source]of Object.entries(attrs))node.setAttribute(key,plain(source));
  document.documentElement.lang=locale;document.title=plain(originalTitle);
  document.querySelectorAll('[data-language]').forEach(button=>{button.classList.toggle('selected',button.dataset.language===locale);button.setAttribute('aria-pressed',String(button.dataset.language===locale));});
 }
 function setLanguage(value){
  const next=value==='en'?'en':'ru',changed=locale!==next;locale=next;
  try{localStorage.setItem('sband_language',locale);}catch(_){}
  staticDOM();if(changed)document.dispatchEvent(new CustomEvent('sband-language',{detail:locale}));
 }
 const ready=fetch('/assets/translations.json',{cache:'no-cache'}).then(r=>{if(!r.ok)throw Error('Translations unavailable');return r.json();}).then(data=>{catalog=data;staticDOM();});
 window.SbandI18n={t,setLanguage,ready,get language(){return locale;},get locale(){return locale==='en'?'en-GB':'ru-RU';}};
 window.SbandT=t;
 // Capture shell text before storefront/admin scripts add any dynamic content.
 staticDOM();
})();
