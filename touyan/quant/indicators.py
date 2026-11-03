"""技术指标。口径对齐国内行情软件（通达信 / 东方财富），方便用户对照核验：

- EMA 以第一个值为初值：EMA_t = (2·X_t + (N−1)·EMA_{t−1}) / (N+1)
- MACD(12,26,9)：DIF = EMA12 − EMA26，DEA = EMA(DIF, 9)，**柱 = 2 × (DIF − DEA)**
  （国内软件的柱子是 2 倍差值；海外软件是 1 倍，数值会差一倍，不是算错）
- RSI：Wilder 平滑，与通达信 SMA(X, N, 1) 等价
- KDJ(9,3,3)：K、D 初值 50，J = 3K − 2D
- BOLL(20,2)：中轨 MA20，带宽用样本标准差
- ATR(14)：Wilder 平滑的真实波幅

所有函数返回与输入等长的列表，数据不足的位置为 None。
"""

from __future__ import annotations

import math


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def ema(values: list[float], n: int) -> list[float]:
    out: list[float] = []
    alpha = 2 / (n + 1)
    for i, v in enumerate(values):
        out.append(v if i == 0 else alpha * v + (1 - alpha) * out[-1])
    return out


def macd(closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """返回 (DIF, DEA, 柱)。前 slow 根数据 EMA 尚未稳定，标为 None。"""
    e_fast, e_slow = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(e_fast, e_slow)]
    dea = ema(dif, signal)
    hist = [2 * (d - e) for d, e in zip(dif, dea)]
    warm = min(len(closes), slow)
    mask = lambda xs: [None] * warm + xs[warm:]  # noqa: E731
    return mask(dif), mask(dea), mask(hist)


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    gain = loss = None
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        up, down = max(diff, 0.0), max(-diff, 0.0)
        if gain is None:
            gain, loss = up, down
        else:
            gain = (up + (n - 1) * gain) / n
            loss = (down + (n - 1) * loss) / n
        if i >= n:
            total = gain + loss
            out[i] = 50.0 if total == 0 else 100 * gain / total
    return out


def kdj(highs: list[float], lows: list[float], closes: list[float], n: int = 9, m1: int = 3, m2: int = 3):
    k_out: list[float | None] = [None] * len(closes)
    d_out: list[float | None] = [None] * len(closes)
    j_out: list[float | None] = [None] * len(closes)
    k = d = 50.0
    for i in range(len(closes)):
        if i < n - 1:
            continue
        hh = max(highs[i - n + 1:i + 1])
        ll = min(lows[i - n + 1:i + 1])
        rsv = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100
        k = ((m1 - 1) * k + rsv) / m1
        d = ((m2 - 1) * d + k) / m2
        k_out[i], d_out[i], j_out[i] = k, d, 3 * k - 2 * d
    return k_out, d_out, j_out


def stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))


def boll(closes: list[float], n: int = 20, k: float = 2.0):
    """返回 (上轨, 中轨, 下轨)。"""
    mid = sma(closes, n)
    up: list[float | None] = [None] * len(closes)
    low: list[float | None] = [None] * len(closes)
    for i in range(n - 1, len(closes)):
        sd = stdev(closes[i - n + 1:i + 1])
        up[i] = mid[i] + k * sd
        low[i] = mid[i] - k * sd
    return up, mid, low


def atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    value = None
    for i in range(len(closes)):
        if i == 0:
            tr = highs[0] - lows[0]
        else:
            tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        value = tr if value is None else (tr + (n - 1) * value) / n
        if i >= n - 1:
            out[i] = value
    return out


def obv(closes: list[float], volumes: list[float]) -> list[float]:
    out: list[float] = []
    total = 0.0
    for i, (c, v) in enumerate(zip(closes, volumes)):
        if i > 0:
            if c > closes[i - 1]:
                total += v
            elif c < closes[i - 1]:
                total -= v
        out.append(total)
    return out


def volume_ratio(volumes: list[float], n: int = 5) -> float | None:
    """量比（日线口径）：今日成交量 / 前 n 日均量。"""
    if len(volumes) < n + 1:
        return None
    base = sum(volumes[-n - 1:-1]) / n
    return volumes[-1] / base if base > 0 else None


def last(values: list) -> float | None:
    """序列最后一个非 None 值。"""
    for v in reversed(values):
        if v is not None:
            return v
    return None


def swing_levels(highs: list[float], lows: list[float], window: int = 5, lookback: int = 120):
    """近 lookback 根 K 线里的波段高点、低点（左右各 window 根内的极值）。返回 (高点[], 低点[])。"""
    n = len(highs)
    start = max(window, n - lookback)
    peaks, troughs = [], []
    for i in range(start, n - window):
        seg_h = highs[i - window:i + window + 1]
        seg_l = lows[i - window:i + window + 1]
        if highs[i] == max(seg_h):
            peaks.append((i, highs[i]))
        if lows[i] == min(seg_l):
            troughs.append((i, lows[i]))
    return peaks, troughs
