"""Push a concise daily summary to Telegram.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. No-ops (with a message) if unset.
Highlights extreme conditions: extreme fear/greed, price crossing STH cost basis,
Pi-Cycle top trigger, large ETF in/outflows.
"""
from __future__ import annotations
import json
import os
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data.json")
SITE = os.environ.get("DASHBOARD_URL", "")


def arrow(x):
    return "🔺" if (x or 0) >= 0 else "🔻"


def pct(x, d=1):
    return "—" if x is None else f"{x*100:+.{d}f}%"


def build_message(d: dict) -> str:
    btc, eth = d["assets"]["BTC"], d["assets"]["ETH"]
    s = d.get("sentiment", {})
    cyc = d.get("cycle", {})
    etf = d.get("etf", {})
    oc = d.get("onchain", {})
    L = []
    L.append("<b>📊 Crypto 行情面板 · 每日</b>")
    L.append(f"<code>{d['meta']['data_date']}</code>")
    L.append("")
    L.append(f"BTC <b>${btc['price']:,.0f}</b>  {arrow(btc['change_24h'])}{pct(btc['change_24h'])} (7d {pct(btc['change_7d'])})")
    L.append(f"ETH <b>${eth['price']:,.0f}</b>  {arrow(eth['change_24h'])}{pct(eth['change_24h'])} (7d {pct(eth['change_7d'])})")
    L.append("")
    L.append(f"😱 恐慌贪婪 <b>{s.get('value','—')}</b> {s.get('label','')}")
    L.append(f"🔄 周期位置 <b>{cyc.get('zone','—')}</b>")
    if etf.get("BTC"):
        L.append(f"💵 BTC ETF 近5日 <b>{etf['BTC']['sum5d']:+.0f}m</b> · ETH {etf['ETH']['sum5d']:+.0f}m" if etf.get("ETH") else
                 f"💵 BTC ETF 近5日 <b>{etf['BTC']['sum5d']:+.0f}m</b>")

    # Alerts
    alerts = []
    if s.get("value") is not None:
        if s["value"] <= 20:
            alerts.append("极度恐慌（逆向关注）")
        elif s["value"] >= 80:
            alerts.append("极度贪婪（警惕过热）")
    sth = oc.get("sthRealizedPrice")
    if sth and btc["price"] < sth:
        alerts.append(f"BTC 跌破短期持有者成本 ${sth:,.0f}（STH 整体亏损）")
    if (cyc.get("pi_cycle") or {}).get("triggered"):
        alerts.append("⚠ Pi Cycle 顶部信号已触发")
    if etf.get("BTC") and etf["BTC"].get("sum5d", 0) <= -1000:
        alerts.append("ETF 大幅净流出（场外资金撤离）")
    if alerts:
        L.append("")
        L.append("⚡ <b>关注</b>：" + "；".join(alerts))

    nar = (d.get("narrative") or {}).get("text")
    if nar:
        first = nar.split("②")[0].strip()  # the short-term paragraph
        L.append("")
        L.append("🤖 " + (first[:300]))
    if SITE:
        L.append("")
        L.append(f'<a href="{SITE}">→ 打开完整面板</a>')
    return "\n".join(L)


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    with open(DATA, "r", encoding="utf-8") as f:
        d = json.load(f)
    msg = build_message(d)
    if not token or not chat:
        print("TELEGRAM_* not set; preview only:\n")
        print(msg)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": msg, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=20,
    )
    print("telegram:", r.status_code, r.text[:200])
    r.raise_for_status()


if __name__ == "__main__":
    main()
