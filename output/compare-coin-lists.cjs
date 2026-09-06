const fs = require('fs');
const path = require('path');
const base = path.resolve(__dirname, '..');
const read = name => JSON.parse(fs.readFileSync(path.join(base, name), 'utf8'));
const config = read('bot_config.json');
const snapshot = read('output/coin-market-snapshot.json');
const targets = new Set(config.target_symbols);
const fee = Number(config.estimated_round_trip_fee_pct) / 200;
const books = new Map(snapshot.books.map(b => [b.symbol, b]));
const ranked = snapshot.tickers.map(t => {
  const b = books.get(t.symbol), bid = Number(b?.bidPrice), ask = Number(b?.askPrice);
  return {symbol:t.symbol, volume:Number(t.quoteVolume), spread: bid > 0 && ask >= bid ? (ask-bid)/((ask+bid)/2)*100 : null};
}).sort((a,b) => b.volume-a.volume || a.symbol.localeCompare(b.symbol));
// A provisional liquidity screen, fixed before examining trade outcomes.
const eligible = ranked.filter(r => r.spread !== null && r.spread <= 0.10);
const lists = [config.target_symbols, eligible.slice(0,20).map(r=>r.symbol), eligible.slice(0,15).map(r=>r.symbol)];
const raw = fs.readFileSync(path.join(base,'transactions.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse);
const seen = new Set();
const transactions = raw.filter(t=>{
  const key = `${t.environment||'unspecified'}:${t.symbol}:${t.side}:${t.order_id}`;
  if(t.order_id != null && seen.has(key)) return false;
  seen.add(key); return t.environment !== 'testnet';
}).sort((a,b)=>a.recorded_at-b.recorded_at);
const buys = new Map(), closed = [];
let excluded = 0;
for(const t of transactions){
  const key = `${t.environment||'unspecified'}:${t.symbol}`;
  if(t.side==='BUY') {buys.set(key,t);continue;}
  if(t.side!=='SELL')continue;
  const buy=buys.get(key);buys.delete(key);
  if(!targets.has(t.symbol))continue;
  const gross=Number(t.estimated_pnl_usdt), proceeds=Number(t.quote_amount);
  if(t.estimated_pnl_usdt==null || !Number.isFinite(gross) || !Number.isFinite(proceeds) || (t.quote_asset && t.quote_asset!=='USDT')){excluded++;continue;}
  // Logged gross P&L provides the cost basis for the quantity actually sold.
  const cost=proceeds-gross;
  if(cost<=0){excluded++;continue;}
  closed.push({symbol:t.symbol,time:t.recorded_at,gross,net:gross-fee*(cost+proceeds),cost,
    automatic:buy?.reason==='strategy buy signal' && ['stop loss','take profit','RSI sell signal'].includes(t.reason),reason:t.reason});
}
function stats(rows){
  let equity=0,peak=0,drawdown=0;
  for(const r of rows){equity+=r.net;peak=Math.max(peak,equity);drawdown=Math.max(drawdown,peak-equity);}
  return {trades:rows.length,net:equity,winRate:rows.length?100*rows.filter(r=>r.net>0).length/rows.length:null,
    average:rows.length?equity/rows.length:null,realizedDrawdown:drawdown,
    fees:rows.reduce((s,r)=>s+r.gross-r.net,0),netPer50:rows.length?rows.reduce((s,r)=>s+50*r.net/r.cost,0)/rows.length:null};
}
const results=lists.map(symbols=>{
  const selected=new Set(symbols),rows=closed.filter(t=>selected.has(t.symbol));
  return {coins:symbols.length,symbols,all:stats(rows),automatic:stats(rows.filter(t=>t.automatic))};
});
const money=n=>n==null?'n/a':n.toFixed(2);
const table=kind=>[
 '| Coins | Closed sells | Est. net USDT | Win rate | Avg. net/sell | Realized drawdown USDT | Est. fees USDT |',
 '|---|---:|---:|---:|---:|---:|---:|',
 ...results.map(r=>{const s=r[kind];return `| ${r.coins} | ${s.trades} | ${money(s.net)} | ${money(s.winRate)}% | ${money(s.average)} | ${money(s.realizedDrawdown)} | ${money(s.fees)} |`;})
].join('\n');
const report = `# Coin-list comparison\n\nPublic market snapshot: ${snapshot.retrieved_at}. Recorded history: ${new Date(transactions[0].recorded_at*1000).toISOString()} to ${new Date(transactions.at(-1).recorded_at*1000).toISOString()}.\n\n## Method\n\nRank the current 30 targets by current 24-hour USDT volume, keeping only current bid/ask spreads at or below 0.10%, then select the first 20 and 15. This provisional threshold is not optimized. Selection does not use recorded profit. Public endpoints: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints .\n\nFilter recorded closed sells to each list; estimate both entry and exit fees at the current configured round-trip rate (${config.estimated_round_trip_fee_pct}%). Gross P&L is the bot's logged estimate. Entry cost for sold quantity is sell proceeds minus logged gross P&L. ${excluded} target sells excluded for missing/invalid values.\n\n## All recorded closed sells (includes manual actions)\n\n${table('all')}\n\n## Matched automatic entries and exits only\n\n${table('automatic')}\n\nAutomatic subset requires the most recent recorded buy to be a strategy buy and the sell reason to be stop loss, take profit, or RSI sell signal. It is a diagnostic subset, not a complete reconstruction of partial fills or accumulated positions.\n\n## Candidate 20\n\n${results[1].symbols.join(', ')}\n\n## Candidate 15\n\n${results[2].symbols.join(', ')}\n\n## Liquidity and per-coin results\n\n| Coin | 24h volume USDT | Current spread % | Closed sells | Est. net USDT |\n|---|---:|---:|---:|---:|\n${ranked.map(r=>{const s=stats(closed.filter(t=>t.symbol===r.symbol));return `| ${r.symbol} | ${r.volume.toFixed(0)} | ${r.spread===null?'unavailable':r.spread.toFixed(4)} | ${s.trades} | ${money(s.net)} |`;}).join('\n')}\n\n## Limits and decision\n\nThis is a retrospective trade-filter comparison, not a strategy backtest or a forecast. Today's liquidity ranking applied to past trades creates look-ahead bias. The history includes changing settings, position sizes and manual trades; it does not establish how the current settings perform. Fewer retained trades usually reduce both total gains/losses and measured drawdown. Realized drawdown is peak-to-trough cumulative closed-trade net P&L in USDT; it excludes unrealized losses and is not portfolio drawdown. Historical spread, commissions and slippage are not recorded; current spread is a snapshot, not historical execution cost. Logged execution prices already reflect fills; no additional historical spread estimate is subtracted. Skipped/replacement trades, four-slot competition and open positions are not simulated. Coins without trades have no performance evidence.\n\nKeep live settings unchanged until a forward paper comparison of the fixed 30/20/15 lists under identical signals, fees, sizing and four-position limits provides independent evidence. The shortlist is saved for that comparison, not proven superior.\n`;
fs.writeFileSync(path.join(__dirname,'coin-list-comparison.md'),report);
fs.writeFileSync(path.join(__dirname,'coin-list-comparison.json'),JSON.stringify({snapshotAt:snapshot.retrieved_at,results,ranked,excluded},null,2));
console.log(JSON.stringify(results,null,2));
