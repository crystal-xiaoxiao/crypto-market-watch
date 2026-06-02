"""Data fetchers for the crypto dashboard.

Every fetcher returns plain dicts/lists and records the source it used so the
frontend can show provenance. Network failures raise SourceError; callers decide
whether to degrade gracefully.

Confirmed-reachable sources (probed 2026-06):
  - Spot OHLCV : data-api.binance.vision  (Binance fapi & Bybit are geo-blocked)
  - Derivatives: OKX public + rubik        (funding / open-interest / long-short)
  - Sentiment  : alternative.me            (Fear & Greed)
  - On-chain   : bitcoin-data.com /v1/*     (MVRV, NUPL, STH cost basis, ...)
  - ETF flows  : farside.co.uk HTML tables  (BTC & ETH spot ETF net flow)
"""
from __future__ import annotations
import os
import re
import time
from typing import List, Optional
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/html"}


class SourceError(Exception):
    pass


def _get(url: str, *, json_out: bool = True, tries: int = 3, timeout: int = 25,
         headers: Optional[dict] = None):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=headers or HEADERS, timeout=timeout)
            if r.status_code == 200:
                return r.json() if json_out else r.text
            last = f"HTTP {r.status_code}"
            if r.status_code == 429:  # rate limited: don't hammer
                break
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {e}"
        if i < tries - 1:
            time.sleep(1.2 * (i + 1))
    raise SourceError(f"{url} failed after {tries} tries: {last}")


# --------------------------------------------------------------------------- #
# Spot OHLCV (Binance public data mirror)
# --------------------------------------------------------------------------- #
def klines(symbol: str, interval: str, limit: int = 1000) -> List[dict]:
    """Return list of candles oldest->newest with float OHLCV + close time(ms)."""
    url = (f"https://data-api.binance.vision/api/v3/klines"
           f"?symbol={symbol}&interval={interval}&limit={limit}")
    raw = _get(url)
    out = []
    for k in raw:
        out.append({
            "open_time": int(k[0]), "open": float(k[1]), "high": float(k[2]),
            "low": float(k[3]), "close": float(k[4]), "volume": float(k[5]),
            "close_time": int(k[6]),
        })
    return out


def spot_ticker_24h(symbol: str) -> dict:
    url = f"https://data-api.binance.vision/api/v3/ticker/24hr?symbol={symbol}"
    j = _get(url)
    return {"last": float(j["lastPrice"]), "change_pct": float(j["priceChangePercent"]) / 100.0}


# --------------------------------------------------------------------------- #
# Derivatives (OKX)
# --------------------------------------------------------------------------- #
def okx_funding(inst: str) -> dict:
    j = _get(f"https://www.okx.com/api/v5/public/funding-rate?instId={inst}")
    d = j["data"][0]
    return {"rate": float(d["fundingRate"]), "next_rate": float(d.get("nextFundingRate") or 0) or None,
            "source": "OKX"}


def okx_open_interest(inst: str) -> dict:
    j = _get(f"https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId={inst}")
    d = j["data"][0]
    return {"oi_contracts": float(d["oi"]), "oi_ccy": float(d["oiCcy"]), "source": "OKX"}


def okx_long_short(ccy: str) -> dict:
    """Latest long/short *account* ratio (1D buckets), plus a short history."""
    j = _get(f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio"
             f"?ccy={ccy}&period=1D")
    data = j["data"]  # newest first: [ts, ratio]
    hist = [{"ts": int(x[0]), "ratio": float(x[1])} for x in data[:30]]
    return {"ratio": hist[0]["ratio"] if hist else None, "history": hist, "source": "OKX"}


# --------------------------------------------------------------------------- #
# Sentiment (alternative.me Fear & Greed)
# --------------------------------------------------------------------------- #
def fear_greed(limit: int = 90) -> dict:
    j = _get(f"https://api.alternative.me/fng/?limit={limit}&format=json")
    data = j["data"]  # newest first
    hist = [{"ts": int(x["timestamp"]), "value": int(x["value"]),
             "label": x["value_classification"]} for x in data]
    return {"value": hist[0]["value"], "label": hist[0]["label"],
            "history": list(reversed(hist)), "source": "alternative.me"}


# --------------------------------------------------------------------------- #
# On-chain & cycle (bitcoin-data.com / bgeometrics) — BTC only
# --------------------------------------------------------------------------- #
_ONCHAIN_KEYS = {
    "mvrv": "mvrv", "mvrv-zscore": "mvrvZscore", "realized-price": "realizedPrice",
    "nupl": "nupl", "sth-mvrv": "sthMvrv", "sth-realized-price": "sthRealizedPrice",
    "puell-multiple": "puellMultiple", "sopr": "sopr",
}


def onchain_latest() -> dict:
    """Fetch the latest value of each bitcoin-data.com metric.

    Free tier is 10 requests/hour, so we make ONE attempt per endpoint (8 total)
    and never retry — that keeps us under budget. Missing metrics come back None;
    build_data.py falls back to the last cached value so the dashboard never blanks.
    An optional BITCOIN_DATA_API_KEY (set out-of-band as a GitHub secret) raises the
    limit and is sent as x-api-key if present.
    """
    out = {"source": "bitcoin-data.com", "date": None, "errors": []}
    key_hdr = dict(HEADERS)
    api_key = os.environ.get("BITCOIN_DATA_API_KEY")
    if api_key:
        key_hdr["x-api-key"] = api_key
    for ep, field in _ONCHAIN_KEYS.items():
        try:
            j = _get(f"https://bitcoin-data.com/v1/{ep}/last", tries=1, headers=key_hdr)
            val = j.get(field)
            out[field] = float(val) if val is not None else None
            if out["date"] is None and j.get("d"):
                out["date"] = j["d"]
        except Exception as e:  # noqa: BLE001
            out[field] = None
            out["errors"].append(ep)
        time.sleep(0.4)
    return out


# --------------------------------------------------------------------------- #
# ETF net flows (farside.co.uk HTML tables) — BTC & ETH
# --------------------------------------------------------------------------- #
def _num(text: str) -> Optional[float]:
    t = (text or "").strip().replace(",", "").replace("$", "")
    if t in ("", "-", "–", "—"):
        return 0.0
    neg = t.startswith("(") and t.endswith(")")
    t = t.strip("()")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def _farside_html(asset: str) -> str:
    """Fetch the farside page HTML.

    Direct works from residential IPs but Cloudflare 403s datacenter IPs (e.g.
    GitHub Actions). Fall back to the keyless Jina reader proxy, which fetches
    server-side and returns the same table HTML.
    """
    direct = f"https://farside.co.uk/{asset}/"
    try:
        return _get(direct, json_out=False, tries=1)
    except SourceError:
        pass
    proxy = f"https://r.jina.ai/https://farside.co.uk/{asset}/"
    hdr = dict(HEADERS)
    hdr["X-Return-Format"] = "html"
    return _get(proxy, json_out=False, tries=2, timeout=45, headers=hdr)


def etf_flows(asset: str) -> dict:
    """Parse farside spot-ETF net-flow table. asset = 'btc' or 'eth'.

    Returns latest daily total net flow ($m), trailing 5-day sum, and cumulative
    total ($m). Flows in USD millions.
    """
    html = _farside_html(asset)
    soup = BeautifulSoup(html, "html.parser")
    date_re = re.compile(r"^\d{1,2} \w{3} \d{4}$")
    # The page has several tables (nav, etc.); pick the one whose first column
    # holds dated rows.
    table = None
    for t in soup.find_all("table"):
        for tr in t.find_all("tr"):
            c0 = tr.find(["td", "th"])
            if c0 and date_re.match(c0.get_text(strip=True)):
                table = t
                break
        if table is not None:
            break
    if table is None:
        raise SourceError(f"farside {asset}: no data table found")
    daily_totals = []  # (date_str, total)
    cumulative = None
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if not cells:
            continue
        label = cells[0]
        # Summary rows
        if label.lower().startswith("total"):
            # last numeric cell of the Total row = grand cumulative net flow
            nums = [_num(c) for c in cells[1:] if _num(c) is not None]
            if nums:
                cumulative = nums[-1]
            continue
        if label.lower() in ("average", "minimum", "maximum") or not any(ch.isdigit() for ch in label):
            continue
        # Data row: a date like "31 May 2026"; last cell is that day's total
        if len(cells) >= 2 and cells[-1]:
            tot = _num(cells[-1])
            if tot is not None:
                daily_totals.append((label, tot))
    if not daily_totals:
        raise SourceError(f"farside {asset}: no data rows parsed")
    # de-dup by date (keep last), preserving order
    seen, deduped = {}, []
    for dt, tot in daily_totals:
        seen[dt] = tot
    for dt, tot in daily_totals:
        if dt in seen:
            deduped.append((dt, seen.pop(dt)))
    daily_totals = deduped
    latest_date, latest = daily_totals[-1]
    last5 = sum(t for _, t in daily_totals[-5:])
    return {"asset": asset.upper(), "latest_date": latest_date, "latest": latest,
            "sum5d": last5, "cumulative": cumulative,
            "recent": [{"date": d, "flow": t} for d, t in daily_totals[-14:]],
            "source": "farside.co.uk"}
