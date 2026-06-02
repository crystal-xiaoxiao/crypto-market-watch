"""Generate the daily Chinese market read with Claude and write it into data.json.

Synthesises the technical / derivatives / on-chain / cycle blocks into:
  1) a 1-3 month directional bias for BTC & ETH,
  2) where we sit in the four-year cycle,
  3) key support/resistance levels (esp. on-chain cost-basis lines, Murphy-style).

Needs ANTHROPIC_API_KEY. Model via CLAUDE_MODEL (default claude-opus-4-8).
If the key is missing or the call fails, leaves any existing narrative untouched.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data.json")
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")


def compact(d: dict) -> dict:
    """Trim payload to what the model needs (drop long history arrays)."""
    def asset(a):
        t = a["technical"]
        return {
            "price": a["price"], "chg_24h": a["change_24h"], "chg_7d": a["change_7d"],
            "chg_30d": a["change_30d"], "rsi_d": t["rsi14_d"], "rsi_w": t["rsi14_w"],
            "ma50": t["ma50"], "ma200": t["ma200"], "macd_hist": t["macd_hist"],
            "mayer": (t["mayer"] or {}).get("mayer"),
            "funding": (a["derivatives"].get("funding") or {}).get("rate"),
            "long_short": (a["derivatives"].get("long_short") or {}).get("ratio"),
            "signals": [f"{s['label']}:{s['value']}({s['state']})" for s in a.get("signals", [])],
        }
    return {
        "BTC": asset(d["assets"]["BTC"]), "ETH": asset(d["assets"]["ETH"]),
        "eth_btc": d["eth_btc"], "fear_greed": {"v": d["sentiment"].get("value"),
                                                 "label": d["sentiment"].get("label")},
        "onchain": {k: d["onchain"].get(k) for k in
                    ("mvrv", "mvrvZscore", "realizedPrice", "nupl", "sthMvrv",
                     "sthRealizedPrice", "puellMultiple", "sopr")},
        "cycle": {"zone": d["cycle"]["zone"], "days_since_halving": d["cycle"]["days_since_halving"],
                  "phase_pct": d["cycle"]["phase_pct"], "pi_triggered": d["cycle"]["pi_cycle"].get("triggered"),
                  "reasons": d["cycle"]["reasons"]},
        "etf": {"BTC": {k: d["etf"]["BTC"].get(k) for k in ("latest", "sum5d", "cumulative")} if d["etf"].get("BTC") else None,
                "ETH": {k: d["etf"]["ETH"].get(k) for k in ("latest", "sum5d", "cumulative")} if d["etf"].get("ETH") else None},
    }


SYSTEM = (
    "你是一位严谨的加密市场分析师，风格接近链上分析师 Murphy(@Murphychen888)："
    "重视链上成本分布与短期持有者(STH)成本作为支撑/压力，用 MVRV/MVRV-Z 判断四年周期位置，"
    "关注 ETF 净流入代表的场外增量资金。基于给定数据写一段中文解读，面向有经验的投资者，"
    "直接、不啰嗦、不堆术语。严禁编造数据里没有的数字。这是研究参考，不是投资建议。"
)

PROMPT = """以下是今日 BTC/ETH 的技术面、衍生品、链上与周期数据(JSON)：

{data}

请输出一段中文解读，约 180–280 字，分三层，用「①②③」标号：
① 短期(1–3个月)：BTC 与 ETH 偏多/偏空/震荡，关键依据(RSI、均线、资金费率、ETF 流向、价 vs STH 成本)。
② 四年周期位置：结合 MVRV-Z、Mayer、Pi Cycle、减半进度，说明现在处于周期的哪个阶段、估值高低。
③ 关键价位：给出当前最重要的支撑/压力(优先用链上成本线，如 STH 成本、Realized Price、年线 MA200)。
最后用一句话给出整体倾向。不要用 markdown 标题，纯文本段落即可。"""


def main():
    with open(DATA, "r", encoding="utf-8") as f:
        d = json.load(f)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY not set; skipping narrative (kept existing).")
        return
    try:
        from anthropic import Anthropic
    except ImportError:
        print("anthropic SDK not installed; skipping narrative.")
        return

    payload = json.dumps(compact(d), ensure_ascii=False, indent=1)
    try:
        client = Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL, max_tokens=900, system=SYSTEM,
            messages=[{"role": "user", "content": PROMPT.format(data=payload)}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    except Exception as e:  # noqa: BLE001
        print(f"narrative generation failed ({type(e).__name__}: {e}); kept existing.")
        return

    if not text:
        print("empty narrative; kept existing.")
        return
    d["narrative"] = {"text": text, "model": MODEL,
                      "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"narrative written ({len(text)} chars, model={MODEL})")
    print("---\n" + text)


if __name__ == "__main__":
    main()
