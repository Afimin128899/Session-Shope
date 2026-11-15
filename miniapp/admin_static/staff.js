'use strict';
const staffOriginalLoad=load;
let advertisingBot='';
load=async function(){
 if(!['advertising','helpers'].includes(page))return staffOriginalLoad();
 const rev=++generation;clearTimeout(stockTimer);const selected=page;
 content.replaceChildren();content.setAttribute('aria-busy','true');$('notice').textContent='';
 try{
  const data=await api(selected);if(rev!==generation)return;
  content.append(node('h2',selected==='helpers'?'Помощник':'Реклама'));
  if(selected==='helpers'){
   content.append(node('p','Одна роль: рекламные ссылки и привлечённые пользователи. Доступа к финансам, товарам и настройкам нет.','muted'));
   content.append(button('Назначить помощника',()=>form('Назначить помощника',[['id','Telegram ID','','text']],async v=>{
    const id=Number(v.id);if(!/^[0-9]+$/.test(v.id)||!Number.isSafeInteger(id)||id<=0)throw Error('Введите Telegram ID.');
    await api('helpers','POST',{user_id:id,enabled:true});
   }),true));
   if(!data.items.length)content.append(node('p','Помощников пока нет. Пользователь должен сначала запустить бота.','muted'));
   for(const user of data.items)row(content,String(user.id),user.username?'@'+user.username:'Без username','',[button('Снять роль',()=>form('Снять роль помощника',[['confirm','Введите Telegram ID для подтверждения','','text']],async v=>{
    if(v.confirm!==String(user.id))throw Error('Укажите ID выбранного помощника.');
    await api('helpers','POST',{user_id:user.id,enabled:false});
   }))]);
  }else{
   advertisingBot=data.bot_username;
   content.append(node('p','Ваши рекламные ссылки. Учитываются новые регистрации после /start, а не клики. Реферальные бонусы не начисляются.','muted'));
   content.append(button('Создать рекламную ссылку',()=>{form('Новая рекламная ссылка',[['name','Название рекламы','','text']],v=>api('advertising','POST',{name:v.name}));$('fields input').maxLength=80;},true));
   if(!data.items.length)content.append(node('p','Рекламных ссылок пока нет.','muted'));
   for(const campaign of data.items){
    const card=node('section',undefined,'ad-campaign'),link=advertisingLink(campaign.token);
    card.append(node('h3',campaign.name),node('p','Новых пользователей: '+campaign.users_count,'ad-count'));
    if(link)card.append(node('code',link,'ad-url'));
    const actions=node('div',undefined,'actions');
    if(link)actions.append(button('Копировать ссылку',async()=>{await navigator.clipboard.writeText(link);$('notice').textContent='Ссылка скопирована.';}));
    actions.append(button('Пользователи',()=>advertisingUsers(campaign.id,0)));card.append(actions);content.append(card);
   }
  }
 }catch(e){if(rev===generation)SbandUI.errorBox(content,e.message,()=>load());}
 finally{if(rev===generation)content.removeAttribute('aria-busy');}
};
function advertisingLink(token){return /^[A-Za-z0-9_]{5,32}$/.test(advertisingBot)&&/^[A-Za-z0-9_-]{22}$/.test(token)?'https://t.me/'+advertisingBot+'?start=ad_'+token:'';}
async function advertisingUsers(id,pageNumber){
 const rev=++generation;content.setAttribute('aria-busy','true');
 try{
  const data=await api('advertising/'+id+'/users?page='+pageNumber);if(rev!==generation)return;
  content.replaceChildren();content.append(node('h2',data.campaign.name),button('Все рекламные ссылки',()=>load()));
  if(!data.items.length)content.append(node('p','По этой ссылке новых пользователей пока нет.','muted'));
  for(const user of data.items){
   const date=new Date(String(user.created_at).replace(' ','T')+'Z');
   row(content,String(user.user_id),user.username?'@'+user.username:'Без username',Number.isNaN(+date)?'':date.toLocaleString('ru-RU',{timeZone:'Europe/Moscow'})+' МСК');
  }
  const pager=node('div',undefined,'pagination');if(pageNumber)pager.append(button('Назад',()=>advertisingUsers(id,pageNumber-1)));if(data.has_more)pager.append(button('Далее',()=>advertisingUsers(id,pageNumber+1)));content.append(pager);
 }catch(e){if(rev===generation){content.replaceChildren();SbandUI.errorBox(content,e.message,()=>load());}}
 finally{if(rev===generation)content.removeAttribute('aria-busy');}
}
