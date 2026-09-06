# Coin-list comparison

Public market snapshot: 2026-09-06T01:37:37.413Z. Recorded history: 2026-08-27T23:47:21.000Z to 2026-09-06T01:15:28.000Z.

## Method

Rank the current 30 targets by current 24-hour USDT volume, keeping only current bid/ask spreads at or below 0.10%, then select the first 20 and 15. This provisional threshold is not optimized. Selection does not use recorded profit. Public endpoints: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints .

Filter recorded closed sells to each list; estimate both entry and exit fees at the current configured round-trip rate (0.2%). Gross P&L is the bot's logged estimate. Entry cost for sold quantity is sell proceeds minus logged gross P&L. 0 target sells excluded for missing/invalid values.

## All recorded closed sells (includes manual actions)

| Coins | Closed sells | Est. net USDT | Win rate | Avg. net/sell | Realized drawdown USDT | Est. fees USDT |
|---|---:|---:|---:|---:|---:|---:|
| 30 | 82 | -1.86 | 48.78% | -0.02 | 4.29 | 3.96 |
| 20 | 69 | -1.61 | 46.38% | -0.02 | 3.81 | 3.19 |
| 15 | 61 | -1.13 | 44.26% | -0.02 | 3.18 | 2.76 |

## Matched automatic entries and exits only

| Coins | Closed sells | Est. net USDT | Win rate | Avg. net/sell | Realized drawdown USDT | Est. fees USDT |
|---|---:|---:|---:|---:|---:|---:|
| 30 | 56 | -2.90 | 41.07% | -0.05 | 3.13 | 2.78 |
| 20 | 47 | -2.71 | 38.30% | -0.06 | 2.81 | 2.22 |
| 15 | 40 | -2.99 | 32.50% | -0.07 | 3.08 | 1.85 |

Automatic subset requires the most recent recorded buy to be a strategy buy and the sell reason to be stop loss, take profit, or RSI sell signal. It is a diagnostic subset, not a complete reconstruction of partial fills or accumulated positions.

## Candidate 20

BNBUSDT, ZECUSDT, DOGEUSDT, MARSCOINUSDT, UNIUSDT, DASHUSDT, SUIUSDT, ARBUSDT, NEARUSDT, ENAUSDT, LTCUSDT, ADAUSDT, PUMPUSDT, TUTUSDT, TRUMPUSDT, ZENUSDT, TAOUSDT, HEMIUSDT, CAKEUSDT, WLDUSDT

## Candidate 15

BNBUSDT, ZECUSDT, DOGEUSDT, MARSCOINUSDT, UNIUSDT, DASHUSDT, SUIUSDT, ARBUSDT, NEARUSDT, ENAUSDT, LTCUSDT, ADAUSDT, PUMPUSDT, TUTUSDT, TRUMPUSDT

## Liquidity and per-coin results

| Coin | 24h volume USDT | Current spread % | Closed sells | Est. net USDT |
|---|---:|---:|---:|---:|
| BNBUSDT | 259883203 | 0.0013 | 0 | 0.00 |
| ZECUSDT | 155004139 | 0.0009 | 5 | -0.42 |
| DOGEUSDT | 120767842 | 0.0110 | 3 | -0.77 |
| MARSCOINUSDT | 87706192 | 0.0397 | 0 | 0.00 |
| UNIUSDT | 82049571 | 0.0136 | 5 | -0.29 |
| ZKCUSDT | 79742984 | 0.1998 | 2 | 0.10 |
| DASHUSDT | 74865700 | 0.0145 | 0 | 0.00 |
| SUIUSDT | 70741193 | 0.0124 | 3 | 0.51 |
| ARBUSDT | 68736816 | 0.0519 | 1 | 0.05 |
| ASTERUSDT | 56692376 | 0.1254 | 4 | -0.39 |
| NEARUSDT | 50135207 | 0.0453 | 6 | -0.42 |
| ENAUSDT | 42842113 | 0.0532 | 7 | 0.73 |
| LTCUSDT | 36014099 | 0.0183 | 4 | -0.72 |
| ADAUSDT | 34129867 | 0.0450 | 9 | 0.63 |
| PUMPUSDT | 33071314 | 0.0256 | 7 | 0.88 |
| TUTUSDT | 31230810 | 0.0354 | 0 | 0.00 |
| TRUMPUSDT | 29624797 | 0.0416 | 11 | -1.31 |
| PEPEUSDT | 28597094 | 0.2743 | 2 | 0.32 |
| ZENUSDT | 23919440 | 0.0140 | 0 | 0.00 |
| TAOUSDT | 22039515 | 0.0420 | 1 | 0.03 |
| HEMIUSDT | 20238919 | 0.0878 | 0 | 0.00 |
| CAKEUSDT | 19395837 | 0.0445 | 1 | 0.18 |
| WLDUSDT | 19337916 | 0.0248 | 6 | -0.69 |
| NOMUSDT | 17467387 | 0.5510 | 0 | 0.00 |
| AAVEUSDT | 14893725 | 0.0072 | 2 | 0.16 |
| PROMUSDT | 14800531 | 0.0398 | 0 | 0.00 |
| 币安人生USDT | 11539166 | 0.0714 | 0 | 0.00 |
| SUSHIUSDT | 11538969 | 0.0774 | 0 | 0.00 |
| FETUSDT | 11065386 | 0.0599 | 3 | -0.45 |
| OPUSDT | 11019053 | 0.0891 | 0 | 0.00 |

## Limits and decision

This is a retrospective trade-filter comparison, not a strategy backtest or a forecast. Today's liquidity ranking applied to past trades creates look-ahead bias. The history includes changing settings, position sizes and manual trades; it does not establish how the current settings perform. Fewer retained trades usually reduce both total gains/losses and measured drawdown. Realized drawdown is peak-to-trough cumulative closed-trade net P&L in USDT; it excludes unrealized losses and is not portfolio drawdown. Historical spread, commissions and slippage are not recorded; current spread is a snapshot, not historical execution cost. Logged execution prices already reflect fills; no additional historical spread estimate is subtracted. Skipped/replacement trades, four-slot competition and open positions are not simulated. Coins without trades have no performance evidence.

Keep live settings unchanged until a forward paper comparison of the fixed 30/20/15 lists under identical signals, fees, sizing and four-position limits provides independent evidence. The shortlist is saved for that comparison, not proven superior.
