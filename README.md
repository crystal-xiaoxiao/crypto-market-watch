# Crypto 行情面板 · BTC / ETH

每日自动更新的 BTC/ETH 行情面板，帮助判断：
- **短期(1–3 个月)走势** — 技术面(RSI/MACD/均线/布林/Mayer)、衍生品(资金费率/持仓量/多空比)、情绪(恐慌贪婪)、**ETF 净流入(场外增量资金)**；
- **四年减半周期位置** — MVRV-Z、Pi Cycle、Mayer Multiple、NUPL、Puell、减半进度；
- **链上筹码(Murphy 框架)** — 短期持有者(STH)成本线、Realized Price 作为支撑/压力，STH-MVRV、SOPR、MVRV。

参考 KOL [@Murphychen888](https://x.com/Murphychen888) 的链上成本分析思路。

## 架构

单个公开仓库，GitHub Actions 每日构建 `docs/data.json` 并提交，GitHub Pages 直接服务 `docs/`。

```
scripts/
  indicators.py     纯 Python 技术指标(无 pandas)，可单测
  sources.py        数据抓取 + 兜底 + 数据源标注
  build_data.py     汇总 → 信号灯 → 周期判断 → docs/data.json
  run_narrative.py  Claude 生成每日中文解读
  notify_telegram.py 推送摘要到 Telegram
docs/
  index.html        单文件前端(Chart.js CDN)
  data.json         构建产物
.github/workflows/daily.yml
```

## 数据源(全部免费)

| 模块 | 来源 |
|---|---|
| 价格/技术面(BTC/ETH 日线+周线) | Binance 公开镜像 `data-api.binance.vision` |
| 衍生品(资金费率/OI/多空比) | OKX 公开端点(Binance/Bybit 在多数云 IP 被封) |
| 情绪(恐慌贪婪) | alternative.me |
| 链上+周期(仅 BTC) | bitcoin-data.com(免费 10 req/hr) |
| ETF 净流入(BTC/ETH) | farside.co.uk |

> 链上筹码/周期指标基本是 BTC 专属；ETH 仅有技术面+衍生品+ETF。
> 完整 URPD 筹码直方图需付费数据，本面板用关键成本线(STH 成本 / Realized Price)替代其核心用法。

## 本地运行

```powershell
pip install -r requirements.txt
python scripts/build_data.py        # 生成 docs/data.json
python scripts/run_narrative.py     # 需 ANTHROPIC_API_KEY，可选
python -m http.server 8765 --directory docs   # 打开 http://localhost:8765
```

## GitHub 配置

Secrets：`ANTHROPIC_API_KEY`、`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`，可选 `BITCOIN_DATA_API_KEY`。
Variables：`DASHBOARD_URL`(面板地址，用于 Telegram 链接)、可选 `CLAUDE_MODEL`。
Pages：从 `main` 分支 `/docs` 目录服务。

## 免责声明

仅供个人投研参考，不构成投资建议。加密资产波动剧烈，注意风险。
