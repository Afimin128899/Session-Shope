// Pure sharing contract: no clipboard access or Telegram messages are sent.
const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const sent=[],box={location:{origin:'https://sbandsub.space',href:'https://sbandsub.space/?tgWebAppData=SECRET#SECRET'},URLSearchParams,navigator:{clipboard:{writeText:async value=>sent.push(value)}},window:{SbandT:s=>s,open:(...args)=>sent.push(args)}};
 vm.runInNewContext(fs.readFileSync('miniapp/static/sharing.js','utf8'),box);
 const share=box.window.SbandSharing;
 assert.equal(share.link('fixture_bot'),'https://t.me/fixture_bot?start=miniapp');
 assert.equal(share.link('bad/bot?SECRET'),'https://sbandsub.space');
 assert.equal(share.link(''),'https://sbandsub.space');
 assert(await share.copy(share.link('fixture_bot')));
 assert(!sent[0].includes('SECRET'));
 let selected=false;box.navigator.clipboard.writeText=async()=>{throw Error('Denied');};
 assert.equal(await share.copy('safe',{focus(){},select(){selected=true;}}),false);assert(selected);
 share.share(share.link('fixture_bot'));
 const u=new URL(sent[1][0]);assert.equal(u.searchParams.get('url'),'https://t.me/fixture_bot?start=miniapp');assert(!u.href.includes('SECRET'));
 console.log('PASS: safe share links, exact clipboard contents, selection fallback and Telegram sharing exclude initData and URL fragments');
})().catch(e=>{console.error(e);process.exitCode=1;});
