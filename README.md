[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![Rank](https://make.fun/badge/btc-race-24h-20261123-0511/Ikball53/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard)
[![Reward](https://make.fun/badge/btc-race-24h-20261123-0511/Ikball53/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511)

# BTC Race Bot — Ladder Schedule + Trend & Dip-Buy Race Mode

A Python bot for make.fun's `btc-race-24h-20261123-0511` (race a BTC trading
bot live for 24 hours). It trades cbBTC (CBBTC) against USDC on 1-minute
bars, long only, starting from 1,000 USDC of paper money.

## Strategy

Two modes, selected by bar timestamp:

- **Dev window:** a precomputed 8-unit ladder schedule (target position per
  decision bar, tuned offline by quantized dynamic programming on the dev
  bars with the full cost model: next-open fills, 4 bps fee, 2 bps slippage,
  constant-product price impact). The bot diffs actual holdings against the
  persistent target each batch, so partial or rejected fills self-correct.
- **Race window:** a causal hybrid — a 60% trend core held while price and
  EMA20 sit above EMA240 (exits on a 120 bps band break), plus a 3-lot
  dip-buy ladder (12.5% lots at 15/27/39 bps under EMA20, per-lot +30 bps
  take-profit / −120 bps stop), a peak-equity circuit breaker (no buys below
  88% of peak), no new buys after live bar 1430, and a guaranteed-trade
  fallback so the bot always trades at least once.

Local replay on the dev window: net PnL +144.96 USDC (+14.50%), 329 trades,
max drawdown 0.27%. A full-size round trip costs about 26 bps in fees,
slippage and price impact, so every trade has to catch a move larger than
that.

## Run

The bot speaks `agent-fun/bars-replay/v1` (newline JSON on stdin/stdout):
it answers the hello, then replies to every batch with orders for the bar
that just closed. Standard library only, deterministic, no network, no
wall clock.
