'use strict';
const beforePartnerLoad=load;
load=async function(){
 if(!['partners','partner-bans','partner-content'].includes(page))return beforePartnerLoad();
 const selected=page,rev=++generation;content.replaceChildren();$('notice').textContent='';content.setAttribute('aria-busy','true');
 try{
  const result=await api(selected);if(rev!==generation)return;
  const heading={partners:'Партнёрские боты','partner-bans':'Общие блокировки','partner-content':'Оформление бота'};
  content.append(node('h2',heading[selected]));
  if(selected==='partners'){
   content.append(node('p','Заявки подаются через /partner в основном боте. После одобрения бот запускается автоматически. Пауза сохраняет деньги; окончательное закрытие переводит внесённые остатки в основной бот, а бонусы аннулирует.','muted'));
   for(const p of result.items){
    const actions=[];
    if(p.status!=='closed'){
     actions.push(button('Одобрить и включить',()=>api('partners','POST',{bot_id:p.bot_id,action:'enable'}).then(()=>load())));
     actions.push(button('Приостановить',()=>api('partners','POST',{bot_id:p.bot_id,action:'pause'}).then(()=>load())));
     actions.push(button('Закрыть и вернуть остатки',()=>form('Закрыть партнёрский бот',[['confirm','Введите ID бота '+p.bot_id+' для закрытия и возврата внесённых остатков','','text']],async v=>{if(v.confirm!==String(p.bot_id))throw Error('ID не совпадает.');await api('partners','POST',{bot_id:p.bot_id,action:'close'});})));
    }
    row(content,'@'+p.username,'Бот '+p.bot_id+' · владелец '+p.owner_id,p.status,actions);
   }
  }else if(selected==='partner-bans'){
   content.append(node('p','Блокировка действует во всех ботах магазина. Вы можете снять только собственную блокировку. Владелец основного бота может снять все.','muted'));
    content.append(button('Заблокировать пользователя',()=>form('Общая блокировка',[['id','ID пользователя','','text'],['reason','Причина','','text']],v=>{const id=v.id.trim();if(!/^[1-9][0-9]{0,18}$/.test(id)||BigInt(id)>=2n**63n)throw Error('Нужен корректный ID пользователя.');return api('partner-bans','POST',{user_id:id,reason:v.reason,enabled:true});}),true));
   for(const b of result.items)row(content,String(b.user_id),b.reason,b.active?'Заблокирован':'Ваша блокировка снята',b.active?[button('Снять свою блокировку',()=>api('partner-bans','POST',{user_id:b.user_id,reason:'Снята партнёром',enabled:false}).then(()=>load()))]:[]);
  }else{
   content.append(node('p','Текст и подписи меняются только для этого бота. Фото загружается через его /admin; для основного бота — через настройки основного бота. Действия кнопок и платёжные настройки не меняются.','muted'));
   const keys=['welcome',...result.labels];
   const labels={welcome:'Приветствие',btn_buy:'Каталог',btn_balance:'Пополнение',btn_profile:'Профиль',btn_support:'Поддержка',btn_purchases:'Покупки',btn_referral_system:'Рефералы',btn_bonuses:'Бонусы',btn_promo:'Промокод',btn_rules:'Правила',btn_user_settings:'Настройки профиля'};
   for(const key of keys)row(content,labels[key]||key,result.content[key]||'Стандартный текст','',[button('Изменить',()=>form('Изменить оформление',[['text',key==='welcome'?'Приветствие до 900 символов; {name} — имя':'Подпись до 50 символов',result.content[key]||'','textarea']],v=>api('partner-content','POST',{key,value:v.text}))) ]);
  }
 }catch(e){if(rev===generation)SbandUI.errorBox(content,e.message,()=>load());}
 finally{if(rev===generation)content.removeAttribute('aria-busy');}
};
