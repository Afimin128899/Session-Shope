'use strict';
window.SbandUI=(()=>{
 const reduced=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
 const paths={market:'M3 9h18M5 9v12h14V9M3 9l2-6h14l2 6M9 21v-7h6v7',messages:'M21 11a8 8 0 0 1-8 8H7l-5 3 2-6a8 8 0 1 1 17-5Z',profile:'M20 21a8 8 0 0 0-16 0M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0',wallet:'M3 6h16v15H3V6Zm0 0 14-4v4m-1 7h5v4h-5v-4Z',search:'M20 20l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',arrow:'m9 5 7 7-7 7'};
 function icon(name){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.classList.add('ui-icon');svg.setAttribute('aria-hidden','true');const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[name]||paths.arrow);svg.append(path);return svg;}
 async function run(button,action){if(button.disabled)return;button.disabled=true;button.classList.add('is-busy');button.setAttribute('aria-busy','true');try{return await action();}finally{button.disabled=false;button.classList.remove('is-busy');button.removeAttribute('aria-busy');}}
 function enter(element){if(!element||reduced())return;element.animate([{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)'});}
 const closing=new WeakMap();
 function open(dialog){closing.get(dialog)?.cancel();closing.delete(dialog);if(!dialog.open)dialog.showModal();}
 async function close(dialog){if(!dialog.open)return;if(!reduced()){const animation=dialog.animate([{opacity:1,transform:'translateY(0)'},{opacity:0,transform:'translateY(12px)'}],{duration:150,easing:'ease-in'});closing.set(dialog,animation);await animation.finished.catch(()=>{});if(closing.get(dialog)!==animation)return;closing.delete(dialog);}dialog.close();}
 function indicator(group){if(group.dataset.indicator)return;group.dataset.indicator='true';group.classList.add('has-selection-track');const track=document.createElement('span');track.className='selection-track';track.setAttribute('aria-hidden','true');group.prepend(track);
  const update=()=>{const selected=group.querySelector('button.selected,button[aria-current=page]');track.hidden=!selected;if(!selected)return;track.style.width=selected.offsetWidth+'px';track.style.height=selected.offsetHeight+'px';track.style.transform=`translate(${selected.offsetLeft}px,${selected.offsetTop}px)`;};
  new ResizeObserver(update).observe(group);new MutationObserver(update).observe(group,{subtree:true,attributes:true,attributeFilter:['class','aria-current']});update();
 }
 function errorBox(parent,message,retry){const box=document.createElement('div');box.className='ui-error-box';box.setAttribute('role','alert');const p=document.createElement('p');p.textContent=message;const b=document.createElement('button');b.type='button';b.textContent='Повторить';b.addEventListener('click',()=>run(b,retry).catch(e=>{p.textContent=e.message;}));box.append(p,b);parent.append(box);return box;}
 let fieldCount=0;
 function fieldError(input,message){let error=document.getElementById(input.dataset.errorId||'');if(!error){error=document.createElement('span');error.className='field-error';error.id='field-error-'+(++fieldCount);input.dataset.errorId=error.id;if(input.parentElement.matches('label'))input.parentElement.insertAdjacentElement('afterend',error);else input.parentElement.append(error);}error.textContent=message;input.setAttribute('aria-invalid',String(Boolean(message)));input.setAttribute('aria-describedby',error.id);}
 document.addEventListener('invalid',event=>{event.preventDefault();const input=event.target;fieldError(input,input.validity.valueMissing?'Заполните это поле.':'Проверьте значение поля.');input.focus();},true);
 document.addEventListener('input',event=>{if(event.target.matches('input,select,textarea')&&event.target.getAttribute('aria-invalid')==='true')fieldError(event.target,'');});
 document.addEventListener('pointerdown',event=>{const b=event.target.closest('button');if(!b||b.disabled||reduced()||!b.animate)return;b.animate([{transform:'scale(1)'},{transform:'scale(.97)'},{transform:'scale(1)'}],{duration:220,easing:'cubic-bezier(.2,.8,.2,1)'});});
 function viewport(){const view=window.visualViewport;const raised=view&&window.innerHeight-view.height>140&&document.activeElement?.matches('input,textarea,select');document.documentElement.classList.toggle('keyboard-open',Boolean(raised));}
 window.visualViewport?.addEventListener('resize',viewport);document.addEventListener('focusin',viewport);document.addEventListener('focusout',()=>setTimeout(viewport,100));
 document.querySelectorAll('.bottom-nav,.segments,nav[aria-label="Разделы администратора"]').forEach(indicator);
 async function request(url,options){let response;try{response=await fetch(url,options);}catch(_){throw Error('Нет соединения. Проверьте интернет и повторите.');}let data;try{data=await response.json();}catch(_){throw Error('Не удалось прочитать ответ. Повторите запрос позже.');}return {response,data};}
 return {run,enter,open,close,indicator,errorBox,fieldError,icon,request};
})();
