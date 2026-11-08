/* Local flag-icons 7.2.3 (MIT); no external image requests. */
(() => {
 'use strict';
 const codes=new Set("ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cp cr cu cv cw cx cy cz de dg dj dk dm do dz ec ee eg eh er es et eu fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu ic id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pc pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um un us uy uz va vc ve vg vi vn vu wf ws xk xx ye yt za zm zw".split(' '));
 function code(item) {
  const category=String(item.category||'').toLowerCase();
  const auto=category.match(/^auto-([a-z]{2})-/);
  const emoji=String(item.name||'').match(/[\u{1F1E6}-\u{1F1FF}]{2}/u)?.[0];
  const value=auto?.[1] || (emoji ? [...emoji].map(c=>String.fromCharCode(c.codePointAt(0)-0x1F1E6+97)).join('') : category);
  return codes.has(value)?value:'unknown';
 }
 window.SbandCountryName=item=>{
  const match=String(item.category||'').match(/^auto-([a-z]{2})-(clear|permanent|limited|pending|unverified)$/);
  if(window.SbandI18n?.language!=='en')return item.name;
  if(!match){
    if(codes.has(String(item.category))){try{return new Intl.DisplayNames(['en'],{type:'region'}).of(item.category.toUpperCase());}catch(_){}}
    return item.name;
  }
  if(!codes.has(match[1]))return item.name;
  const status={clear:'No spam restrictions',permanent:'Permanent spam restriction',limited:'Spam restrictions',pending:'Spam check pending',unverified:'Spam status unverified'};
  try{return new Intl.DisplayNames(['en'],{type:'region'}).of(match[1].toUpperCase())+' · '+status[match[2]];}catch(_){return item.name;}
 };
 window.SbandCountryArt=item=>`<img class="country-image" src="/assets/flags/${code(item)}.svg" alt="" width="160" height="120" loading="lazy" decoding="async">`;
})();
