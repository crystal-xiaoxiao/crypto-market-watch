"""Build docs/data.json — the single payload the dashboard renders.

Pipeline: fetch raw sources -> compute technical indicators & signals ->
assemble cycle/on-chain/ETF/sentiment blocks -> merge cached on-chain values
(so a transient rate-limit never blanks the page) -> write JSON.

Run locally:  python scripts/build_data.py
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone, date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indicators as ind
import sources as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data.json")

HALVING_DATE = date(2024, 4, 20)      # 4th Bitcoin halving
CYCLE_DAYS = 1458                      # ~4 years between halvings

# Historical "halving -> bear-market bottom" intervals, from the prior 3 cycles.
# Used to project this cycle's bottoming window (what Crystal wants: "how long
# until the historically-typical bottom"). Note: the bottom has consistently
# landed ~2.1-2.5 yr after the halving; ~1.5 yr post-halving was the cycle TOP.
HISTORICAL_CYCLES = [
    {"halving": "2012-11-28", "top": "2013-11-30", "bottom": "2015-01-14",
     "top_offset": 367, "bottom_offset": 777},
    {"halving": "2016-07-09", "top": "2017-12-17", "bottom": "2018-12-15",
     "top_offset": 526, "bottom_offset": 889},
    {"halving": "2020-05-11", "top": "2021-11-10", "bottom": "2022-11-21",
     "top_offset": 548, "bottom_offset": 924},
]


def closes(candles):
    return [c["close"] for c in candles]


def pct(a, b):
    return (a / b - 1.0) if (a and b) else None


# --------------------------------------------------------------------------- #
# Per-asset technical block
# --------------------------------------------------------------------------- #
def build_asset(symbol: str, name: str, daily, weekly, deriv) -> dict:
    dc = closes(daily)
    wc = closes(weekly)
    price = dc[-1]
    macd_line, macd_sig, macd_hist = ind.macd(dc)
    mid, up, lo, pctb = ind.bollinger(dc, 20)
    block = {
        "symbol": symbol, "name": name, "price": price,
        "change_24h": pct(dc[-1], dc[-2]) if len(dc) > 1 else None,
        "change_7d": pct(dc[-1], dc[-8]) if len(dc) > 8 else None,
        "change_30d": pct(dc[-1], dc[-31]) if len(dc) > 31 else None,
        "technical": {
            "rsi14_d": ind.rsi(dc, 14),
            "rsi14_w": ind.rsi(wc, 14),
            "ma20": ind.sma(dc, 20), "ma50": ind.sma(dc, 50),
            "ma100": ind.sma(dc, 100), "ma200": ind.sma(dc, 200),
            "ma200w": ind.sma(wc, 200),
            "macd": macd_line, "macd_signal": macd_sig, "macd_hist": macd_hist,
            "boll_mid": mid, "boll_up": up, "boll_low": lo, "boll_pctb": pctb,
            "mayer": ind.mayer_multiple(dc),
        },
        "derivatives": deriv,
    }
    return block


# --------------------------------------------------------------------------- #
# Signal helpers — each returns {label, state, value, note}
# state in {bull, bear, caution, neutral}
# --------------------------------------------------------------------------- #
def sig(label, state, value, note):
    return {"label": label, "state": state, "value": value, "note": note}


def asset_signals(a: dict) -> list:
    out = []
    t = a["technical"]
    price = a["price"]
    rsi = t["rsi14_d"]
    if rsi is not None:
        if rsi >= 70:
            out.append(sig("RSI(日)", "caution", f"{rsi:.0f}", "超买，短期回调风险"))
        elif rsi <= 30:
            out.append(sig("RSI(日)", "bull", f"{rsi:.0f}", "超卖，短期反弹机会"))
        else:
            out.append(sig("RSI(日)", "neutral", f"{rsi:.0f}", "中性"))
    ma50, ma200 = t["ma50"], t["ma200"]
    if ma50 and ma200:
        if ma50 > ma200:
            out.append(sig("均线结构", "bull", "MA50>MA200", "多头排列（金叉之上）"))
        else:
            out.append(sig("均线结构", "bear", "MA50<MA200", "空头排列（死叉之下）"))
    if ma200:
        st = "bull" if price > ma200 else "bear"
        out.append(sig("价 vs MA200", st, f"{(price/ma200-1)*100:+.1f}%",
                       "处于年线之上" if price > ma200 else "跌破年线"))
    if t["macd_hist"] is not None:
        st = "bull" if t["macd_hist"] > 0 else "bear"
        out.append(sig("MACD柱", st, f"{t['macd_hist']:+.0f}",
                       "动能向上" if t["macd_hist"] > 0 else "动能向下"))
    d = a["derivatives"]
    fr = d.get("funding", {}).get("rate")
    if fr is not None:
        if fr >= 0.0005:
            out.append(sig("资金费率", "caution", f"{fr*100:.3f}%", "多头过热，拥挤"))
        elif fr < 0:
            out.append(sig("资金费率", "bull", f"{fr*100:.3f}%", "空头付费，情绪偏空（常见局部底）"))
        else:
            out.append(sig("资金费率", "neutral", f"{fr*100:.3f}%", "正常区间"))
    ls = d.get("long_short", {}).get("ratio")
    if ls is not None:
        if ls >= 2.0:
            out.append(sig("多空账户比", "caution", f"{ls:.2f}", "散户过度做多，留意反向"))
        else:
            out.append(sig("多空账户比", "neutral", f"{ls:.2f}", "未见极端"))
    return out


def etf_signal(etf: dict) -> dict:
    s5 = etf.get("sum5d")
    if s5 is None:
        return sig("ETF 5日净流入", "neutral", "—", "数据缺失")
    if s5 > 200:
        return sig("ETF 5日净流入", "bull", f"+${s5:.0f}m", "场外资金净流入（看多）")
    if s5 < -200:
        return sig("ETF 5日净流入", "bear", f"${s5:.0f}m", "场外资金净流出（看空）")
    return sig("ETF 5日净流入", "neutral", f"${s5:+.0f}m", "资金面中性")


# --------------------------------------------------------------------------- #
# On-chain interpretation (BTC, Murphy-style)
# --------------------------------------------------------------------------- #
def onchain_block(oc: dict, btc_price: float, prev: dict) -> dict:
    """Map raw bitcoin-data values into interpreted fields; fall back to cache."""
    def val(field):
        v = oc.get(field)
        if v is None and prev:
            v = (prev.get("onchain", {}) or {}).get(field)
            if v is not None:
                stale.add(field)
        return v
    stale = set()
    mvrv = val("mvrv"); mvrvz = val("mvrvZscore"); rp = val("realizedPrice")
    nupl = val("nupl"); sth_mvrv = val("sthMvrv"); sth_rp = val("sthRealizedPrice")
    puell = val("puellMultiple"); sopr = val("sopr")

    signals = []
    # STH cost basis = key short-term support/resistance (Murphy's core lens)
    if sth_rp and btc_price:
        below = btc_price < sth_rp
        signals.append(sig("价 vs 短期持有者成本", "bear" if below else "bull",
                           f"${sth_rp:,.0f}",
                           "价在 STH 成本之下：短期持有者整体亏损，常见恐慌/筑底区"
                           if below else "价在 STH 成本之上：短期持有者获利，成本线转为支撑"))
    if sth_mvrv is not None:
        if sth_mvrv < 1:
            signals.append(sig("STH-MVRV", "bull", f"{sth_mvrv:.2f}", "短期持有者亏损，抛压释放中"))
        elif sth_mvrv > 1.3:
            signals.append(sig("STH-MVRV", "caution", f"{sth_mvrv:.2f}", "短期持有者获利丰厚，留意获利了结"))
        else:
            signals.append(sig("STH-MVRV", "neutral", f"{sth_mvrv:.2f}", "中性"))
    if sopr is not None:
        signals.append(sig("SOPR", "bull" if sopr < 1 else "neutral", f"{sopr:.3f}",
                           "整体在亏损卖出（投降）" if sopr < 1 else "整体获利了结"))
    return {
        "mvrv": mvrv, "mvrvZscore": mvrvz, "realizedPrice": rp, "nupl": nupl,
        "sthMvrv": sth_mvrv, "sthRealizedPrice": sth_rp, "puellMultiple": puell,
        "sopr": sopr, "date": oc.get("date") or (prev.get("onchain", {}) or {}).get("date"),
        "stale_fields": sorted(stale), "signals": signals,
    }


# --------------------------------------------------------------------------- #
# Four-year cycle position
# --------------------------------------------------------------------------- #
def cycle_block(btc_daily, oc: dict, mayer: dict, today: date) -> dict:
    dc = closes(btc_daily)
    pi = ind.pi_cycle_top(dc)
    days_since = (today - HALVING_DATE).days
    phase_pct = max(0.0, min(1.0, days_since / CYCLE_DAYS))
    mvrvz = oc.get("mvrvZscore")
    nupl = oc.get("nupl")

    # Verdict from MVRV-Z (primary cycle valuation gauge)
    if mvrvz is None:
        zone, state = "数据缺失", "neutral"
    elif mvrvz < 0:
        zone, state = "周期底部区（深度低估）", "bull"
    elif mvrvz < 2:
        zone, state = "周期早中段（估值偏低-中性）", "bull"
    elif mvrvz < 4:
        zone, state = "周期中后段（估值升高）", "caution"
    elif mvrvz < 6:
        zone, state = "周期顶部区（高估，warning）", "bear"
    else:
        zone, state = "极度高估（历史顶部信号）", "bear"

    reasons = []
    if mvrvz is not None:
        reasons.append(f"MVRV-Z={mvrvz:.2f}")
    if mayer.get("mayer") is not None:
        reasons.append(f"Mayer={mayer['mayer']:.2f}（{mayer['zone']}）")
    if pi["ratio"] is not None:
        reasons.append("Pi Cycle " + ("已触发顶部信号" if pi["triggered"]
                       else f"未触发(比值{pi['ratio']:.2f})"))
    if nupl is not None:
        reasons.append(f"NUPL={nupl:.2f}")

    bottom = bottom_projection(days_since, today)
    return {
        "halving_date": HALVING_DATE.isoformat(), "days_since_halving": days_since,
        "phase_pct": phase_pct, "next_halving_eta_days": max(0, CYCLE_DAYS - days_since),
        "pi_cycle": pi, "mayer": mayer, "mvrvZscore": mvrvz, "nupl": nupl,
        "puell": oc.get("puellMultiple"), "realizedPrice": oc.get("realizedPrice"),
        "zone": zone, "state": state, "reasons": reasons,
        "bottom": bottom, "historical_cycles": HISTORICAL_CYCLES,
        "top_window": {  # for the timeline (historical top zone)
            "start_offset": min(c["top_offset"] for c in HISTORICAL_CYCLES),
            "end_offset": max(c["top_offset"] for c in HISTORICAL_CYCLES),
        },
    }


def bottom_projection(days_since: int, today: date) -> dict:
    """Project this cycle's bear-bottom window from the prior 3 cycles' offsets.

    Answers Crystal's question directly: how many days until the historically-
    typical bottom (window low / median / high), and whether we're before, inside,
    or past that window.
    """
    offsets = sorted(c["bottom_offset"] for c in HISTORICAL_CYCLES)  # 777, 889, 924
    lo, mid, hi = offsets[0], offsets[len(offsets) // 2], offsets[-1]
    mean = round(sum(offsets) / len(offsets))

    def proj_date(off):
        return (HALVING_DATE + timedelta(days=off)).isoformat()

    if days_since < lo:
        phase = "before"      # 还没进入历史熊底窗口
    elif days_since <= hi:
        phase = "within"      # 正处于历史熊底窗口
    else:
        phase = "after"       # 已越过历史熊底窗口
    return {
        "offsets": offsets, "median_offset": mid, "mean_offset": mean,
        "window_start_date": proj_date(lo), "median_date": proj_date(mid),
        "window_end_date": proj_date(hi),
        "days_to_window_start": lo - days_since,
        "days_to_median": mid - days_since,
        "days_to_window_end": hi - days_since,
        "phase": phase,
    }


# --------------------------------------------------------------------------- #
def load_prev() -> dict:
    if os.path.exists(OUT):
        try:
            with open(OUT, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            return {}
    return {}


def safe(fn, default, warnings, label):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        warnings.append(f"{label}: {type(e).__name__}: {e}")
        return default


def main():
    warnings = []
    prev = load_prev()
    today = datetime.now(timezone.utc).date()

    btc_d = safe(lambda: S.klines("BTCUSDT", "1d", 1000), [], warnings, "BTC daily")
    btc_w = safe(lambda: S.klines("BTCUSDT", "1w", 400), [], warnings, "BTC weekly")
    eth_d = safe(lambda: S.klines("ETHUSDT", "1d", 1000), [], warnings, "ETH daily")
    eth_w = safe(lambda: S.klines("ETHUSDT", "1w", 400), [], warnings, "ETH weekly")
    if not btc_d or not eth_d:
        raise SystemExit("FATAL: no price data; aborting (keeping previous data.json)")

    btc_deriv = {
        "funding": safe(lambda: S.okx_funding("BTC-USDT-SWAP"), {}, warnings, "BTC funding"),
        "open_interest": safe(lambda: S.okx_open_interest("BTC-USDT-SWAP"), {}, warnings, "BTC OI"),
        "long_short": safe(lambda: S.okx_long_short("BTC"), {}, warnings, "BTC L/S"),
    }
    eth_deriv = {
        "funding": safe(lambda: S.okx_funding("ETH-USDT-SWAP"), {}, warnings, "ETH funding"),
        "open_interest": safe(lambda: S.okx_open_interest("ETH-USDT-SWAP"), {}, warnings, "ETH OI"),
        "long_short": safe(lambda: S.okx_long_short("ETH"), {}, warnings, "ETH L/S"),
    }

    btc = build_asset("BTCUSDT", "Bitcoin", btc_d, btc_w, btc_deriv)
    eth = build_asset("ETHUSDT", "Ethereum", eth_d, eth_w, eth_deriv)
    btc["signals"] = asset_signals(btc)
    eth["signals"] = asset_signals(eth)

    fng = safe(lambda: S.fear_greed(90), {}, warnings, "Fear&Greed")
    oc_raw = safe(lambda: S.onchain_latest(), {}, warnings, "on-chain")
    etf_btc = safe(lambda: S.etf_flows("btc"), {}, warnings, "ETF BTC")
    etf_eth = safe(lambda: S.etf_flows("eth"), {}, warnings, "ETF ETH")

    onchain = onchain_block(oc_raw, btc["price"], prev)
    cycle = cycle_block(btc_d, onchain, btc["technical"]["mayer"], today)

    # ETH/BTC ratio (trend tells alt-season vs BTC dominance)
    eth_btc = eth["price"] / btc["price"] if btc["price"] else None
    btc_dc, eth_dc = closes(btc_d), closes(eth_d)
    ratio_30d_ago = (eth_dc[-31] / btc_dc[-31]) if len(btc_dc) > 31 else None
    eth_btc_block = {"ratio": eth_btc,
                     "change_30d": pct(eth_btc, ratio_30d_ago) if ratio_30d_ago else None}

    if etf_btc:
        btc["signals"].append(etf_signal(etf_btc))
    if etf_eth:
        eth["signals"].append(etf_signal(etf_eth))

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "data_date": today.isoformat(),
            "warnings": warnings,
            "sources": {
                "price": "Binance (data.binance.vision)", "derivatives": "OKX",
                "sentiment": "alternative.me", "onchain": "bitcoin-data.com",
                "etf": "farside.co.uk",
            },
        },
        "assets": {"BTC": btc, "ETH": eth},
        "eth_btc": eth_btc_block,
        "sentiment": fng,
        "onchain": onchain,
        "cycle": cycle,
        "etf": {"BTC": etf_btc, "ETH": etf_eth},
        "narrative": prev.get("narrative"),  # preserved; refreshed by run_narrative.py
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"wrote {OUT}")
    print(f"  BTC ${btc['price']:,.0f}  ETH ${eth['price']:,.0f}  ETH/BTC {eth_btc:.4f}")
    print(f"  cycle: {cycle['zone']}  | warnings: {len(warnings)}")
    for w in warnings:
        print("   !", w)


if __name__ == "__main__":
    main()
