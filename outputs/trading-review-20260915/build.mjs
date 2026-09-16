import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const out='outputs/trading-review-20260915';
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const issues=[];
async function lines(p){const text=await fs.readFile(p,'utf8');return text.split(/\r?\n/).flatMap((l,i)=>{if(!l.trim())return [];try{return [{...JSON.parse(l),source_line:i+1,raw_json:l}]}catch(e){issues.push(`${p}:${i+1}: invalid JSON`);return []}})}
const all=await lines('transactions.jsonl');
const end=Math.max(...all.map(r=>r.recorded_at)),start=end-5*86400;
const tx=all.filter(r=>r.recorded_at>=start&&r.recorded_at<=end).sort((a,b)=>a.recorded_at-b.recorded_at);
const market=await lines('market_overview_history.jsonl');
const controls=await lines('control_changes.jsonl');
const config=await read('bot_config.json'), state=await read('trade_state.json');
const local=t=>new Date((t+10800)*1000),utc=t=>new Date(t*1000);
const day=t=>local(t).toISOString().slice(0,10);
function flat(o,p='',a={}){for(const [k,v] of Object.entries(o)){const key=p?`${p}.${k}`:k;if(v&&typeof v==='object'&&!Array.isArray(v))flat(v,key,a);else a[key]=Array.isArray(v)?JSON.stringify(v):v}return a}
const numeric=/^(quantity|price|quote_amount|estimated_pnl_usdt|net_pnl_usdt|commission_quote|base_commission_quantity|base_commission_quote|remaining_quantity|remaining_cost_basis_quote|cost_basis_quote|entry|stop_loss|take_profit|strategy_take_profit)$/;
function typed(o){return Object.fromEntries(Object.entries(o).map(([k,v])=>[k,k.includes('order_id')?String(v):numeric.test(k)&&v!==null&&v!==''?Number(v):v]))}
const txrows=tx.map(r=>{const m=market.filter(m=>m.environment===r.environment&&m.recorded_at<=r.recorded_at).at(-1);return {...typed(flat(r)),has_recorded_net:r.net_pnl_usdt!=null?1:0,time_riyadh:local(r.recorded_at),time_utc:utc(r.recorded_at),local_date:day(r.recorded_at),pnl_basis:r.pnl_status??'gross only; actual fees not recorded',market_regime:m?.regime??'Unavailable',market_snapshot_riyadh:m?local(m.recorded_at):null,market_snapshot_age_seconds:m?r.recorded_at-m.recorded_at:null,failed_entry_checks:r.entry_conditions?Object.entries(r.entry_conditions).filter(([k,v])=>v===false).map(([k])=>k).join(', '):null}});
// Link to the latest preceding BUY only when no intervening BUY makes the entry ambiguous.
const active=new Map(),matches=[];
for(const r of [...all].sort((a,b)=>a.recorded_at-b.recorded_at)){
const key=`${r.environment}:${r.symbol}`;
if(r.side==='BUY'){const prev=active.get(key);active.set(key,{buy:r,ambiguous:!!prev});}
if(r.side==='SELL'){
 const entry=active.get(key);
 if(r.recorded_at>=start&&r.recorded_at<=end){const b=entry?.buy;matches.push({symbol:r.symbol,environment:r.environment,sell_order_id:String(r.order_id),exit_riyadh:local(r.recorded_at),reason:r.reason,buy_order_id:b?String(b.order_id):null,entry_riyadh:b?local(b.recorded_at):null,match_status:!b?'No preceding buy':entry.ambiguous?'Multiple buys; latest entry shown':'Latest preceding buy; inferred',holding_minutes:b?(r.recorded_at-b.recorded_at)/60:null,entry_price:b?Number(b.price):null,exit_price:Number(r.price),sold_quantity:Number(r.quantity),gross_pnl_recorded:r.estimated_pnl_usdt!=null?Number(r.estimated_pnl_usdt):null,net_pnl_recorded:r.net_pnl_usdt!=null?Number(r.net_pnl_usdt):null,pnl_basis:r.pnl_status??'gross only; actual fees not recorded',entry_source_line:b?.source_line??null,exit_source_line:r.source_line,entry_before_window:b?b.recorded_at<start:null,...(b?flat({entry_conditions:b.entry_conditions??{}}):{})});}
 if(!r.remaining_quantity||Number(r.remaining_quantity)===0||r.remaining_is_dust)active.delete(key);
}
}
const wb=Workbook.create();
function col(n){let s='';for(n++;n;n=Math.floor((n-1)/26))s=String.fromCharCode(65+(n-1)%26)+s;return s}
const sheets=[];
function table(name,rows,preferred=[],source=''){
 const sh=wb.worksheets.add(name);sheets.push(sh);sh.showGridLines=false;
 const keys=[...new Set([...preferred,...rows.flatMap(Object.keys)])];
 sh.getRange('A2').values=[[name]];sh.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#183153'};
 sh.getRange('A3').values=[[source]];
 const n=Math.max(rows.length,1),last=col(keys.length-1);
 sh.getRange(`A5:${last}5`).values=[keys];
 if(rows.length)sh.getRange(`A6:${last}${rows.length+5}`).values=rows.map(r=>keys.map(k=>r[k]??null));
 sh.getRange(`A5:${last}${n+5}`).format.font={name:'Arial',size:10};
 sh.getRange(`A5:${last}${n+5}`).format.rowHeight=21;
 sh.getRange(`A5:${last}5`).format={fill:'#183153',font:{bold:true,color:'#FFFFFF'},wrapText:true,rowHeight:44};
 for(let i=0;i<keys.length;i++){
  const k=keys[i],rng=sh.getRange(`${col(i)}6:${col(i)}${n+5}`);
  rng.format.columnWidth=k==='raw_json'?70:/time|riyadh|utc|snapshot/.test(k)?24:/reason|status|basis|checks/.test(k)?32:20;
  if(k==='saved_at'||rows.some(r=>r[k] instanceof Date))rng.setNumberFormat('yyyy-mm-dd hh:mm:ss');
  else if(rows.some(r=>typeof r[k]==='number'))rng.setNumberFormat(/line|seconds|recorded_at|buys|sells|records|wins|losses|sample_size|has_recorded/.test(k)?'0':'0.00000000;[Red](0.00000000);0');
 }
 if(name==='Current settings'){sh.getRange('A6:A50').format.columnWidth=38;sh.getRange('B6:B50').format.columnWidth=100;sh.getRange('B6').format.wrapText=true;sh.getRange('B6').format.rowHeight=100;}
 if(name==='Market history'){const idx=keys.indexOf('expectation');sh.getRange(`${col(idx)}6:${col(idx)}${n+5}`).format.columnWidth=80;}
 if(rows.length)sh.tables.add(`A5:${last}${rows.length+5}`,true,name.replace(/[^a-z]/gi,'')+'Table');
 sh.freezePanes.freezeRows(5);
 return {sh,keys,n:rows.length};
}
const summary=wb.worksheets.add('Summary');sheets.push(summary);summary.showGridLines=false;
const t=table('Transactions',txrows,['time_riyadh','symbol','side','order_id','quantity','price','quote_amount','estimated_pnl_usdt','net_pnl_usdt','pnl_basis','reason','environment','source_line'],'Source: transactions.jsonl. All original fields retained, including exact raw JSON.');
table('Trade review',matches,['exit_riyadh','symbol','reason','gross_pnl_recorded','net_pnl_recorded','pnl_basis','holding_minutes','match_status'],'Source: transactions.jsonl, including pre-window buys. Links are inferred, not exchange lot accounting.');
const summarize=(name,keys,field)=>{const data=keys.map(k=>({[name]:k,buys:0,sells:0,gross_pnl:0,known_net_pnl:null,net_records:0,gross_wins:0,gross_losses:0,gross_win_rate:null}));const x=table(name==='Date'?'Daily summary':'Coin summary',data,[],`Source: Transactions. Gross excludes fees. Known net totals cover only rows with recorded net P&L.`);const ref=k=>`'Transactions'!$${col(t.keys.indexOf(k))}$6:$${col(t.keys.indexOf(k))}$${t.n+5}`;for(let i=0;i<keys.length;i++){let r=i+6;const f=ref(field),side=ref('side'),gross=ref('estimated_pnl_usdt'),net=ref('net_pnl_usdt');x.sh.getRange(`B${r}:I${r}`).formulas=[[`=COUNTIFS(${f},A${r},${side},"BUY")`,`=COUNTIFS(${f},A${r},${side},"SELL")`,`=SUMIFS(${gross},${f},A${r},${side},"SELL")`,`=IF(F${r}=0,"",SUMIFS(${net},${f},A${r},${side},"SELL"))`,`=SUMIFS(${ref("has_recorded_net")},${f},A${r},${side},"SELL")`,`=COUNTIFS(${f},A${r},${side},"SELL",${gross},">0")`,`=COUNTIFS(${f},A${r},${side},"SELL",${gross},"<0")`,`=IF(G${r}+H${r}=0,"",G${r}/(G${r}+H${r}))`]];}x.sh.getRange(`I6:I${keys.length+5}`).setNumberFormat('0.0%');return x;};
const daily=summarize('Date',[...new Set(tx.map(r=>day(r.recorded_at)))],'local_date');
summarize('Symbol',[...new Set(tx.map(r=>r.symbol))].sort(),'symbol');
table('Market history',market.filter(r=>r.recorded_at>=start&&r.recorded_at<=end).map(r=>({time_riyadh:local(r.recorded_at),...typed(flat(r))})),[],'Source: market_overview_history.jsonl. Recorded market-wide context, not individual coin candles.');
table('Control changes',controls.filter(r=>r.recorded_at>=start&&r.recorded_at<=end).map(r=>({time_riyadh:local(r.recorded_at),...flat(r)})),[],'Source: control_changes.jsonl. Only changes actually logged are available.');
table('Current positions',Object.values(state.positions??{}).map(r=>typed(flat(r))),['symbol','quantity','entry','stop_loss','take_profit'],'Source: trade_state.json, snapshot at export. Current positions are not historical closing balances.');
table('Current settings',Object.entries(flat(config)).map(([setting,value])=>({setting,value})),[],'Source: bot_config.json, snapshot at export. These settings must not be assumed to apply to earlier trades.');
const notes=[
 ['Period start (Riyadh)',local(start)],['Period end (Riyadh)',local(end)],['Transactions',tx.length],['Buy executions',tx.filter(r=>r.side==='BUY').length],['Sell executions',tx.filter(r=>r.side==='SELL').length],['Gross P&L (USDT)',null],['Sells with recorded net P&L',tx.filter(r=>r.side==='SELL'&&r.net_pnl_usdt!=null).length],['Source parsing issues',issues.length],['Period definition','Rolling 120 hours ending at latest logged transaction; first and last calendar days may be partial.'],['Profit limitation','Gross P&L is the bot-recorded estimate before commissions. Blank net is unknown, not zero. No historical fee estimates were invented.'],['Trade matching','Latest preceding BUY is shown for review. Multiple buys and missing entries are flagged; holding time for ambiguous matches is indicative.'],['Scope','Production transaction file only. Testnet files excluded. All transaction fields and exact source JSON preserved.'],['Precision','Numeric cells use Excel precision. Exact original decimal strings and identifiers remain in raw_json.'],['Missing history','Historical per-coin indicators, order-book spreads, exchange fills and commissions are not available unless recorded in source rows.'],['Snapshot notes','Current positions and settings were captured at export, not reconstructed at the period boundary.'],['Exported UTC',new Date()]
];
summary.getRange('A2').values=[['Five-day trading review']];summary.getRange('A2').format.font={name:'Arial',size:15,bold:true,color:'#183153'};
summary.getRange(`A5:B${notes.length+4}`).values=notes;summary.getRange(`A5:B${notes.length+4}`).format.font={name:'Arial',size:11};summary.getRange('A5:A20').format.columnWidth=34;summary.getRange('B5:B20').format.columnWidth=100;summary.getRange('B5:B6').setNumberFormat('yyyy-mm-dd hh:mm:ss');summary.getRange('B20').setNumberFormat('yyyy-mm-dd hh:mm:ss');summary.getRange('A5:B20').format.rowHeight=33;summary.getRange('B13:B19').format.wrapText=true;
summary.getRange('B10').formulas=[[`=SUM('Daily summary'!D6:D${daily.n+5})`]];summary.getRange('B10').setNumberFormat('0.0000;[Red](0.0000)');
wb.recalculate();
console.log((await wb.inspect({kind:'table',range:'Summary!A5:B12',include:'values,formulas',tableMaxRows:8,tableMaxCols:2})).ndjson);
console.log((await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!',options:{useRegex:true,maxResults:20}})).ndjson);
await (await SpreadsheetFile.exportXlsx(wb)).save(`${out}/Trading_Report_Last_5_Days.xlsx`);
for(const sh of sheets){try{const pic=await wb.render({sheetName:sh.name,range:sh.name==='Summary'?'A2:B12':'A2:F10',scale:1,format:'png'});await fs.writeFile(`${out}/${sh.name.replaceAll(' ','_')}.png`,new Uint8Array(await pic.arrayBuffer()));}catch(e){console.log('RENDER',sh.name,e.message)}}
console.log(JSON.stringify({transactions:tx.length,sells:matches.length,start:local(start),end:local(end),gross:tx.reduce((n,r)=>n+Number(r.estimated_pnl_usdt??0),0),issues}));
