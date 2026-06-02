"""Pure-Python technical indicators (no pandas/numpy needed).

All functions take a list of floats (oldest -> newest) and return either a
single latest value or a list aligned to the input (None where undefined).
"""
from __future__ import annotations
from typing import List, Optional


def sma(values: List[float], period: int) -> Optional[float]:
    """Simple moving average of the last `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def sma_series(values: List[float], period: int) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < period:
            out.append(None)
        else:
            out.append(sum(values[i + 1 - period:i + 1]) / period)
    return out


def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """Exponential moving average; seeded with the SMA of the first `period`."""
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values: List[float], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI of the latest bar."""
    if len(values) <= period:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = values[i] - values[i - 1]
        gains += max(ch, 0.0)
        losses += max(-ch, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(values)):
        ch = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(ch, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-ch, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(values: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram) latest values, or (None,None,None)."""
    if len(values) < slow + signal:
        return (None, None, None)
    ef = ema_series(values, fast)
    es = ema_series(values, slow)
    macd_line = [ (a - b) if (a is not None and b is not None) else None
                  for a, b in zip(ef, es) ]
    macd_vals = [m for m in macd_line if m is not None]
    sig = ema_series(macd_vals, signal)
    if not sig or sig[-1] is None:
        return (macd_line[-1], None, None)
    m = macd_line[-1]
    s = sig[-1]
    return (m, s, (m - s) if (m is not None and s is not None) else None)


def bollinger(values: List[float], period: int = 20, mult: float = 2.0):
    """Returns (middle, upper, lower, pctB) for the latest bar."""
    if len(values) < period:
        return (None, None, None, None)
    window = values[-period:]
    mid = sum(window) / period
    var = sum((x - mid) ** 2 for x in window) / period
    sd = var ** 0.5
    upper, lower = mid + mult * sd, mid - mult * sd
    last = values[-1]
    pctb = (last - lower) / (upper - lower) if upper != lower else None
    return (mid, upper, lower, pctb)


def pi_cycle_top(daily_closes: List[float]):
    """Pi Cycle Top: 111DMA vs 2x350DMA. Returns dict with both lines + ratio.

    A cross of 111DMA above 2x350DMA historically marks cycle tops.
    ratio = 111DMA / (2*350DMA); >=1 means the top signal has triggered.
    """
    ma111 = sma(daily_closes, 111)
    ma350 = sma(daily_closes, 350)
    if ma111 is None or ma350 is None:
        return {"ma111": ma111, "ma350x2": (ma350 * 2 if ma350 else None),
                "ratio": None, "triggered": None}
    ma350x2 = ma350 * 2
    ratio = ma111 / ma350x2 if ma350x2 else None
    return {"ma111": ma111, "ma350x2": ma350x2, "ratio": ratio,
            "triggered": (ratio is not None and ratio >= 1.0)}


def mayer_multiple(daily_closes: List[float]):
    """Mayer Multiple = price / 200-day SMA. A clean, data-driven valuation gauge.

    Historically: > 2.4 overheated (cycle-top risk), ~1.0 fair, < 1.0 undervalued,
    < 0.8 deep-value. Returns dict with the multiple, the 200DMA and a zone label.
    """
    ma200 = sma(daily_closes, 200)
    if ma200 is None or ma200 == 0 or not daily_closes:
        return {"mayer": None, "ma200": ma200, "zone": None}
    price = daily_closes[-1]
    mm = price / ma200
    if mm >= 2.4:
        zone = "过热 · 周期顶部风险"
    elif mm >= 1.5:
        zone = "偏热 · 牛市中后段"
    elif mm >= 1.0:
        zone = "中性偏强 · 趋势之上"
    elif mm >= 0.8:
        zone = "偏弱 · 趋势之下"
    else:
        zone = "深度低估 · 历史抄底区"
    return {"mayer": mm, "ma200": ma200, "zone": zone}
