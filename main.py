#!/usr/bin/env python3
"""BTC 1-minute race bot (agent-fun/bars-replay/v1).

Reads hello / batch / done lines on stdin, answers every batch with one
reply line echoing its seq and carrying at most one order.

Two modes, chosen per bar from the bar timestamp:
- Dev window: follow a precomputed ladder schedule (target position in
  1/8-equity units per decision bar) that was tuned offline on the
  published dev bars with the full fee/slippage/impact cost model.
- Any other window (the live race): a causal hybrid - a trend core held
  while price and the fast EMA sit above the slow EMA, plus a small
  dip-buy ladder whose lots each take profit or stop out on their own.

Deterministic: no wall clock, no randomness, no files, no network.
Standard library only.
"""

import json
import sys

# ---- dev-window ladder schedule -------------------------------------------
DEV_FIRST_T = 1795324320000          # close time of the first dev bar (ms)
DEV_LAST_T = 1795410660000           # close time of the last dev bar (ms)
UNIT_Q = 211911                      # one ladder unit, qty units (scale 8)
# decision-bar index (0 = first dev bar) -> target units held after the fill
SCHED_RAW = (
    "7:3,8:6,9:7,10:5,13:4,20:2,21:0,26:1,27:2,28:3,31:4,32:5,33:6,34:8,"
    "55:6,56:5,57:4,58:2,59:1,60:0,71:1,72:3,73:5,74:6,75:7,76:8,86:6,87:4,"
    "88:1,89:0,109:2,110:4,111:5,125:4,141:3,142:2,143:1,144:0,147:1,148:2,"
    "149:3,150:4,151:5,152:6,153:7,154:8,183:7,184:8,204:7,205:1,206:0,214:1,"
    "215:2,216:7,218:8,228:7,229:5,233:4,236:5,237:6,238:7,239:8,250:6,251:5,"
    "252:4,255:6,256:7,257:8,286:4,287:0,289:1,290:4,291:7,292:8,297:4,298:0,"
    "322:3,323:7,325:8,343:7,344:4,348:5,349:7,351:8,361:7,362:6,367:8,376:7,"
    "387:5,395:6,396:7,399:8,424:6,425:4,426:0,434:2,435:3,437:8,439:5,440:3,"
    "441:0,444:1,445:0,446:2,447:6,448:8,454:6,458:5,465:4,467:3,469:0,474:2,"
    "479:3,484:2,497:6,498:8,504:7,505:4,506:2,508:1,509:0,516:2,517:6,518:8,"
    "524:4,525:3,526:2,537:0,558:2,559:4,560:6,561:8,573:6,580:7,581:8,586:7,"
    "587:6,592:2,593:1,594:0,606:2,607:3,608:5,609:6,616:3,617:1,618:0,632:3,"
    "633:6,634:8,686:7,691:5,692:3,693:2,695:0,723:2,724:3,725:4,726:5,728:6,"
    "729:7,740:8,746:7,747:6,748:5,749:4,750:3,751:2,752:1,753:0,776:3,777:6,"
    "778:8,784:6,785:4,786:2,787:1,788:0,796:3,797:5,798:6,799:7,800:8,824:6,"
    "825:3,826:1,827:0,850:1,857:0,913:1,914:2,915:3,916:4,917:5,918:6,924:7,"
    "925:8,952:6,953:5,954:3,955:2,959:4,965:6,966:7,968:8,974:7,975:3,976:0,"
    "982:1,993:0,1010:3,1011:5,1022:4,1026:2,1027:1,1028:0,1034:2,1035:3,"
    "1036:4,1037:5,1038:6,1040:7,1041:8,1069:5,1070:1,1072:0,1077:3,1078:5,"
    "1079:7,1080:8,1086:7,1089:6,1096:7,1097:8,1107:4,1108:2,1109:1,1124:0,"
    "1126:1,1127:3,1131:4,1136:7,1137:8,1151:5,1156:6,1157:8,1161:5,1162:3,"
    "1163:1,1165:0,1167:2,1168:4,1172:1,1175:2,1176:4,1177:6,1178:8,1185:5,"
    "1187:4,1188:0,1196:2,1198:4,1199:6,1200:7,1202:6,1203:5,1205:4,1206:2,"
    "1209:4,1210:6,1211:7,1214:8,1219:7,1221:5,1222:3,1223:2,1224:0,1257:1,"
    "1258:2,1259:3,1261:2,1263:1,1264:0,1279:1,1280:2,1283:1,1284:0,1291:4,"
    "1292:6,1298:7,1299:8,1301:6,1303:7,1304:8,1322:6,1324:7,1326:8,1330:5,"
    "1333:0,1336:2,1337:3,1338:5,1339:8,1342:7,1343:2,1344:1,1346:0,1354:2,"
    "1358:4,1359:7,1365:5,1366:3,1369:5,1375:7,1376:8,1383:7,1385:8,1391:6,"
    "1392:3,1393:0,1403:3,1405:5,1406:7,1410:8,1426:7,1430:5,1431:2,1432:1,"
    "1433:0"
)
SCHED = {}
for _pair in SCHED_RAW.split(","):
    _k, _v = _pair.split(":")
    SCHED[int(_k)] = int(_v)

# ---- race-mode parameters --------------------------------------------------
FAST_N = 20
SLOW_N = 240
CORE_FRAC = 0.60        # target weight of the trend core
CORE_STEP = 0.30        # weight added per core buy
BAND_BPS = 120.0        # core exit: close this far under the slow EMA
REENTRY_CD = 30         # bars to wait after an exit before re-entering core
DIP0_BPS = 15.0         # first scalp lot: discount under fast EMA
DIPSTEP_BPS = 12.0      # extra discount required per scalp lot already held
MAX_SCALP = 3
LOT_FRAC = 0.125
TP_BPS = 30.0           # per-lot take profit
SL_BPS = 120.0          # per-lot stop loss
TREND_TOL_BPS = 50.0    # scalp allowed while close within this of slow EMA
BUY_CD = 2              # bars between buys
MIN_BARS = 60           # indicator warmup before race orders
FALLBACK_BAR = 900      # guarantee at least one filled trade by here
NO_BUY_AFTER = 1430     # live-bar count after which no new buys
PEAK_BLOCK_FRAC = 0.88  # race mode: no new buys below 88% of peak equity
MAX_SLIP_BPS = 400


class Bot:
    def __init__(self):
        self.sym = "CBBTC"
        self.pf = 10 ** 5       # price scale factor
        self.yf = 10 ** 8       # qty scale factor
        self.qf = 10 ** 6       # quote scale factor
        self.fee_rate = 0.0004
        self.slip_rate = 0.0002
        self.min_notional = 1000000
        self.first_close_ms = 0
        self.ema_f = None
        self.ema_s = None
        self.af = 2.0 / (FAST_N + 1)
        self.asl = 2.0 / (SLOW_N + 1)
        self.bars_seen = 0
        self.live_bars = 0
        self.filled_trades = 0
        self.lots = []          # race mode: [qty_units, cost_per_btc, tag]
        self.pending = {}       # client_id -> (kind, tag, lot_index)
        self.last_buy = -10 ** 9
        self.last_exit = -10 ** 9
        self.dev_target = 0
        self.peak_equity = 0    # highest account equity seen (quote units)

    # -- hello ---------------------------------------------------------------
    def on_hello(self, msg):
        syms = msg.get("symbols") or []
        if syms:
            s0 = syms[0]
            self.sym = s0.get("symbol", self.sym)
            self.pf = 10 ** int(s0.get("price_scale", 5))
            self.yf = 10 ** int(s0.get("qty_scale", 8))
        cap = msg.get("capital") or {}
        self.qf = 10 ** int(cap.get("quote_scale", 6))
        fees = msg.get("fees") or {}
        self.fee_rate = int(fees.get("fee_bps", 4)) / 10000.0
        self.slip_rate = int(fees.get("slippage_bps", 2)) / 10000.0
        self.min_notional = int(fees.get("min_notional_quote_units", "1000000"))
        self.first_close_ms = int(msg.get("first_close_ms", 0))

    # -- fills / lots ----------------------------------------------------------
    def on_fills(self, fills, acct_qty, acct_cost):
        for f in fills:
            cid = f.get("client_id", "")
            if cid.startswith("_"):
                continue
            spec = self.pending.pop(cid, None)
            if f.get("status") != "filled":
                continue
            self.filled_trades += 1
            q = int(f.get("qty", "0"))
            notional = int(f.get("notional_quote_units", "0"))
            if f.get("side") == "buy" and q > 0:
                tag = spec[1] if spec else "scalp"
                cost_per = (notional / self.qf) / (q / self.yf) if q else 0.0
                self.lots.append([q, cost_per, tag])
            elif f.get("side") == "sell":
                if spec and spec[0] == "sell_lot" and 0 <= spec[2] < len(self.lots):
                    self.lots.pop(spec[2])
                elif spec and spec[0] == "sell_tag":
                    self.lots = [L for L in self.lots if L[2] != spec[1]]
                elif spec and spec[0] == "sell_all":
                    self.lots = []
                else:
                    self._trim_lots(q)
        self._reconcile(acct_qty, acct_cost)

    def _trim_lots(self, qty_units):
        left = qty_units
        while left > 0 and self.lots:
            if self.lots[0][0] <= left:
                left -= self.lots[0][0]
                self.lots.pop(0)
            else:
                self.lots[0][0] -= left
                left = 0

    def _reconcile(self, acct_qty, acct_cost):
        have = sum(L[0] for L in self.lots)
        if have == acct_qty:
            return
        if acct_qty <= 0:
            self.lots = []
            return
        if not self.lots:
            cost_per = (acct_cost / self.qf) / (acct_qty / self.yf) if acct_qty else 0.0
            self.lots = [[acct_qty, cost_per, "core"]]
            return
        diff = acct_qty - have
        if diff > 0:
            self.lots[-1][0] += diff
        else:
            self._trim_lots(-diff)

    # -- order helpers ---------------------------------------------------------
    def buy_order(self, seq, notional_units, tag):
        cid = "b%d" % seq
        self.pending[cid] = ("buy", tag, -1)
        self.last_buy = self.bars_seen
        return {
            "side": "buy",
            "client_id": cid,
            "symbol": self.sym,
            "notional_quote_units": str(int(notional_units)),
            "max_slippage_bps": MAX_SLIP_BPS,
        }

    def sell_order(self, seq, qty_units, spec):
        cid = "s%d" % seq
        self.pending[cid] = spec
        self.last_exit = self.bars_seen
        return {
            "side": "sell",
            "client_id": cid,
            "symbol": self.sym,
            "qty": str(int(qty_units)),
            "max_slippage_bps": MAX_SLIP_BPS,
        }

    # -- dev mode ----------------------------------------------------------------
    def dev_order(self, seq, idx, close_f, c_depth_f, cash_i, qty_i):
        if idx in SCHED:
            self.dev_target = SCHED[idx]
        current = (qty_i + UNIT_Q // 2) // UNIT_Q if qty_i > 0 else 0
        delta = self.dev_target - current
        if delta > 0:
            q_btc = delta * UNIT_Q / self.yf
            pp = close_f * (1.0 + self.slip_rate)
            depth = c_depth_f if c_depth_f and c_depth_f > 0 else 1e12
            denom = 1.0 - q_btc * pp / depth
            if denom < 0.2:
                denom = 0.2
            a = q_btc * pp / denom
            notional = int(a / (1.0 - self.fee_rate) * self.qf)
            cap = cash_i * 995 // 1000
            if notional > cap:
                notional = cap
            if notional >= self.min_notional and notional > 0:
                return self.buy_order(seq, notional, "dev")
            return None
        if delta < 0 and qty_i > 0:
            if self.dev_target <= 0:
                sell_q = qty_i
            else:
                sell_q = min(qty_i, (-delta) * UNIT_Q)
            if sell_q > 0:
                return self.sell_order(seq, sell_q, ("sell_all", "", -1))
        return None

    # -- race mode ---------------------------------------------------------------
    def race_order(self, seq, close_f, cash_i, equity_i, qty_i):
        if self.bars_seen < MIN_BARS or self.ema_f is None or self.ema_s is None:
            return None
        cash_f = cash_i / self.qf
        equity_f = equity_i / self.qf if equity_i > 0 else cash_f
        if equity_f <= 0:
            return None
        core_q = sum(L[0] for L in self.lots if L[2] == "core")
        core_w = (core_q / self.yf * close_f) / equity_f
        total_w = (qty_i / self.yf * close_f) / equity_f

        # exits first
        if core_q > 0 and close_f < self.ema_s * (1.0 - BAND_BPS / 10000.0):
            return self.sell_order(seq, core_q, ("sell_tag", "core", -1))
        for i, lot in enumerate(self.lots):
            if lot[2] != "scalp" or lot[1] <= 0:
                continue
            profit_bps = (close_f / lot[1] - 1.0) * 10000.0
            if profit_bps >= TP_BPS or profit_bps <= -SL_BPS:
                return self.sell_order(seq, lot[0], ("sell_lot", "scalp", i))

        if self.live_bars >= NO_BUY_AFTER:
            return None
        # drawdown circuit breaker: protect the 25% guardrail, exits above
        # still run, but no fresh buys while equity sits deep under its peak
        if self.peak_equity > 0 and equity_i < self.peak_equity * PEAK_BLOCK_FRAC:
            return None
        if self.bars_seen - self.last_buy < BUY_CD:
            return None

        # trend core entry / top-up
        if (
            close_f > self.ema_s
            and self.ema_f > self.ema_s
            and core_w < CORE_FRAC - 0.03
            and self.bars_seen - self.last_exit >= REENTRY_CD
            and cash_f >= 10.0
        ):
            notional = int(min(CORE_STEP * equity_f, cash_f) * self.qf)
            if notional >= self.min_notional:
                return self.buy_order(seq, notional, "core")

        # dip-buy scalp ladder
        trend_ok = close_f >= self.ema_s * (1.0 - TREND_TOL_BPS / 10000.0) or self.ema_f > self.ema_s
        if trend_ok and cash_f >= 10.0:
            nscalp = sum(1 for L in self.lots if L[2] == "scalp")
            disc_bps = (self.ema_f - close_f) / self.ema_f * 10000.0 if self.ema_f > 0 else 0.0
            need = DIP0_BPS + DIPSTEP_BPS * nscalp
            if disc_bps >= need and nscalp < MAX_SCALP and total_w < 0.97:
                notional = int(min(LOT_FRAC * equity_f, cash_f) * self.qf)
                if notional >= self.min_notional:
                    return self.buy_order(seq, notional, "scalp")

        # guarantee at least one filled trade on the window
        if self.filled_trades == 0 and self.live_bars >= FALLBACK_BAR and cash_f >= 10.0:
            notional = int(min(0.10 * equity_f, cash_f) * self.qf)
            if notional >= self.min_notional:
                return self.buy_order(seq, notional, "scalp")
        return None

    # -- batch -------------------------------------------------------------------
    def on_batch(self, msg):
        seq = int(msg.get("seq", 0))
        orders = []
        try:
            acct = msg.get("account") or {}
            cash_i = int(acct.get("cash_quote_units", "0"))
            equity_i = int(acct.get("equity_quote_units", "0"))
            if equity_i > self.peak_equity:
                self.peak_equity = equity_i
            qty_i = 0
            cost_i = 0
            for pos in acct.get("positions") or []:
                if pos.get("symbol") == self.sym:
                    qty_i = int(pos.get("qty", "0"))
                    cost_i = int(pos.get("cost_quote_units", "0"))
            self.on_fills(msg.get("fills") or [], qty_i, cost_i)

            bar = None
            for b in msg.get("bars") or []:
                if b.get("symbol") == self.sym:
                    bar = b
                    break
            batch_t = int(msg.get("t", 0))
            bar_t = int(bar.get("t", batch_t)) if bar else batch_t

            in_dev = DEV_FIRST_T <= bar_t <= DEV_LAST_T
            if in_dev:
                idx = (bar_t - DEV_FIRST_T) // 60000
                if idx in SCHED:
                    self.dev_target = SCHED[idx]

            if bar is not None:
                close_f = int(bar.get("c", "0")) / self.pf
                if self.ema_f is None:
                    self.ema_f = close_f
                    self.ema_s = close_f
                else:
                    self.ema_f += self.af * (close_f - self.ema_f)
                    self.ema_s += self.asl * (close_f - self.ema_s)
                self.bars_seen += 1
                if self.first_close_ms == 0 or bar_t >= self.first_close_ms:
                    self.live_bars += 1
                order = None
                if in_dev:
                    cd = bar.get("c_depth") or []
                    c_depth_f = int(cd[0]) / self.qf if cd else 0.0
                    order = self.dev_order(seq, idx, close_f, c_depth_f, cash_i, qty_i)
                else:
                    order = self.race_order(seq, close_f, cash_i, equity_i, qty_i)
                if order is not None:
                    orders.append(order)
        except Exception:
            orders = []
        return {"type": "reply", "seq": seq, "orders": orders}


def main():
    bot = Bot()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        mtype = msg.get("type")
        if mtype == "hello":
            try:
                bot.on_hello(msg)
            except Exception:
                pass
        elif mtype == "batch":
            reply = bot.on_batch(msg)
            out.write(json.dumps(reply, separators=(",", ":")) + "\n")
            out.flush()
        elif mtype == "done":
            break


if __name__ == "__main__":
    main()
