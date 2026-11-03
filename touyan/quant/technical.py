"""技术面：指标序列、支撑压力位、信号解读。

每条信号都带「依据」——具体是哪几个数造成的，用户能拿行情软件对照验证。
信号只描述结构（多头排列、超买、放量下跌……），不做「明天涨」这类预测。

场外基金只有净值、没有高低价和成交量：KDJ、量价类信号自动跳过，
不拿 o=h=l=c 的伪 K 线算出一堆没意义的数。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from market.models import Bar
from quant import indicators as ind


@dataclass
class Signal:
    key: str
    name: str
    dimension: str     # trend / momentum / risk / valuation / quality / growth / ...
    impact: float      # 对维度分的加减（正 = 偏多/更好）
    value: str         # 关键数值
    detail: str        # 解读（依据）

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(x: float | None, digits: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def _fmt(x: float | None, digits: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:,.{digits}f}" if abs(x) < 1e6 else f"{x:,.0f}"


def compute(bars: list[Bar]) -> dict:
    """计算全部指标序列与最新值。"""
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    vols = [b.volume for b in bars]
    has_ohlc = any(b.high != b.low for b in bars[-60:])
    has_volume = any(v > 0 for v in vols[-60:])
    dif, dea, hist = ind.macd(closes)
    up, mid, low = ind.boll(closes)
    k, d, j = ind.kdj(highs, lows, closes) if has_ohlc else ([None] * len(bars),) * 3
    series = {
        "ma5": ind.sma(closes, 5), "ma10": ind.sma(closes, 10), "ma20": ind.sma(closes, 20),
        "ma60": ind.sma(closes, 60), "ma120": ind.sma(closes, 120), "ma250": ind.sma(closes, 250),
        "boll_up": up, "boll_mid": mid, "boll_low": low,
        "dif": dif, "dea": dea, "macd": hist,
        "rsi6": ind.rsi(closes, 6), "rsi14": ind.rsi(closes, 14),
        "k": k, "d": d, "j": j,
        "atr14": ind.atr(highs, lows, closes) if has_ohlc else [None] * len(bars),
        "vol_ma5": ind.sma(vols, 5) if has_volume else [None] * len(bars),
        "vol_ma20": ind.sma(vols, 20) if has_volume else [None] * len(bars),
    }
    latest = {name: ind.last(values) for name, values in series.items()}
    latest["close"] = closes[-1]
    latest["volume_ratio"] = ind.volume_ratio(vols) if has_volume else None
    return {"series": series, "latest": latest, "has_ohlc": has_ohlc, "has_volume": has_volume}


def levels(bars: list[Bar], tech: dict) -> dict:
    """支撑 / 压力位：近半年波段高低点 + 均线 + 布林带，以及 52 周区间和 ATR。"""
    close = bars[-1].close
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]
    peaks, troughs = ind.swing_levels(highs, lows)
    res = sorted({round(p, 4): bars[i].date for i, p in peaks if p > close * 1.003}.items())
    sup = sorted({round(t, 4): bars[i].date for i, t in troughs if t < close * 0.997}.items(), reverse=True)
    resistances = [{"price": p, "label": f"波段高点（{d}）"} for p, d in res[:2]]
    supports = [{"price": p, "label": f"波段低点（{d}）"} for p, d in sup[:2]]
    lt = tech["latest"]
    for key, label in (("ma20", "20日均线"), ("ma60", "60日均线"), ("ma250", "年线"), ("boll_low", "布林下轨"), ("boll_up", "布林上轨")):
        v = lt.get(key)
        if v is None:
            continue
        (resistances if v > close else supports).append({"price": round(v, 4), "label": label})
    resistances.sort(key=lambda x: x["price"])
    supports.sort(key=lambda x: -x["price"])
    window = bars[-250:]
    hi52, lo52 = max(b.high for b in window), min(b.low for b in window)
    atr = lt.get("atr14")
    return {
        "supports": supports[:4],
        "resistances": resistances[:4],
        "high_52w": hi52,
        "low_52w": lo52,
        "pos_52w": (close - lo52) / (hi52 - lo52) if hi52 > lo52 else None,
        "atr": atr,
        "atr_pct": atr / close if atr else None,
    }


def _cross(a: list, b: list, within: int) -> int:
    """最近 within 根内 a 上穿 b 返回 1，下穿返回 -1，否则 0（取最近一次）。"""
    n = len(a)
    for i in range(n - 1, max(0, n - within) - 1, -1):
        if None in (a[i], b[i], a[i - 1], b[i - 1]):
            return 0
        if a[i - 1] <= b[i - 1] and a[i] > b[i]:
            return 1
        if a[i - 1] >= b[i - 1] and a[i] < b[i]:
            return -1
    return 0


def _ret(bars: list[Bar], n: int) -> float | None:
    return bars[-1].adj_close / bars[-n - 1].adj_close - 1 if len(bars) > n else None


def signals(bars: list[Bar], tech: dict) -> list[Signal]:
    s = tech["series"]
    lt = tech["latest"]
    close = lt["close"]
    out: list[Signal] = []

    # ── 趋势 ──
    ma5, ma20, ma60, ma250 = lt["ma5"], lt["ma20"], lt["ma60"], lt["ma250"]
    if None not in (ma5, ma20, ma60):
        vals = f"MA5 {_fmt(ma5)} / MA20 {_fmt(ma20)} / MA60 {_fmt(ma60)}"
        if ma5 > ma20 > ma60:
            strong = close > ma5
            out.append(Signal("ma_align", "均线排列", "trend", 15 if strong else 12, vals,
                              "短中期均线呈多头排列" + ("，价格站上全部均线" if strong else "") + "，趋势向上"))
        elif ma5 < ma20 < ma60:
            weak = close < ma5
            out.append(Signal("ma_align", "均线排列", "trend", -15 if weak else -12, vals,
                              "短中期均线呈空头排列" + ("，价格位于全部均线之下" if weak else "") + "，趋势向下"))
        else:
            out.append(Signal("ma_align", "均线排列", "trend", 0, vals, "均线相互交织，趋势不明朗，处于整理阶段"))
    if ma60:
        gap = close / ma60 - 1
        if abs(gap) > 0.01:
            out.append(Signal("ma60", "中期趋势", "trend", 6 if gap > 0 else -6, f"偏离 MA60 {_pct(gap)}",
                              f"价格{'高于' if gap > 0 else '低于'} 60 日均线 {abs(gap) * 100:.1f}%"))
    if ma250:
        gap = close / ma250 - 1
        out.append(Signal("ma250", "长期趋势", "trend", 8 if gap > 0 else -8, f"偏离年线 {_pct(gap)}",
                          f"价格{'站上' if gap > 0 else '跌破'}年线（250 日均线），长期趋势{'偏多' if gap > 0 else '偏弱'}"))
    m20 = [v for v in s["ma20"][-6:] if v is not None]
    if len(m20) == 6:
        slope = m20[-1] / m20[0] - 1
        if abs(slope) > 0.01:
            out.append(Signal("ma20_slope", "20日均线方向", "trend", 5 if slope > 0 else -5, f"5 日变化 {_pct(slope)}",
                              f"20 日均线{'向上' if slope > 0 else '向下'}倾斜"))
    dif, dea = lt["dif"], lt["dea"]
    if dif is not None and dea is not None:
        if dif > 0 and dea > 0:
            out.append(Signal("macd_zone", "MACD 位置", "trend", 5, f"DIF {_fmt(dif, 3)} / DEA {_fmt(dea, 3)}", "DIF、DEA 均在零轴上方，多头区域"))
        elif dif < 0 and dea < 0:
            out.append(Signal("macd_zone", "MACD 位置", "trend", -5, f"DIF {_fmt(dif, 3)} / DEA {_fmt(dea, 3)}", "DIF、DEA 均在零轴下方，空头区域"))

    # ── 动量 ──
    r20, r60 = _ret(bars, 20), _ret(bars, 60)
    if r20 is not None:
        impact = 8 if r20 > 0.08 else 4 if r20 > 0.03 else -8 if r20 < -0.08 else -4 if r20 < -0.03 else 0
        out.append(Signal("ret20", "20日涨跌", "momentum", impact, _pct(r20), f"近 20 个交易日{'上涨' if r20 >= 0 else '下跌'} {abs(r20) * 100:.1f}%"))
    if r60 is not None:
        impact = 6 if r60 > 0.15 else 3 if r60 > 0.05 else -6 if r60 < -0.15 else -3 if r60 < -0.05 else 0
        out.append(Signal("ret60", "60日涨跌", "momentum", impact, _pct(r60), f"近 60 个交易日{'上涨' if r60 >= 0 else '下跌'} {abs(r60) * 100:.1f}%"))
    cross = _cross(s["dif"], s["dea"], 5)
    hist = [h for h in s["macd"][-3:] if h is not None]
    if cross:
        out.append(Signal("macd_cross", "MACD 交叉", "momentum", 8 * cross, "近 5 日" + ("金叉" if cross > 0 else "死叉"),
                          "DIF 上穿 DEA 形成金叉，动能转强" if cross > 0 else "DIF 下穿 DEA 形成死叉，动能转弱"))
    elif len(hist) == 3:
        if hist[-1] > 0 and hist[-1] > hist[-2] > hist[-3]:
            out.append(Signal("macd_hist", "MACD 柱", "momentum", 4, f"柱 {_fmt(hist[-1], 3)}", "红柱连续放大，上涨动能增强"))
        elif hist[-1] < 0 and hist[-1] < hist[-2] < hist[-3]:
            out.append(Signal("macd_hist", "MACD 柱", "momentum", -4, f"柱 {_fmt(hist[-1], 3)}", "绿柱连续放大，下跌动能增强"))
        elif hist[-1] > 0 and hist[-1] < hist[-2]:
            out.append(Signal("macd_hist", "MACD 柱", "momentum", -1, f"柱 {_fmt(hist[-1], 3)}", "红柱缩短，上涨动能减弱"))
        elif hist[-1] < 0 and hist[-1] > hist[-2]:
            out.append(Signal("macd_hist", "MACD 柱", "momentum", 1, f"柱 {_fmt(hist[-1], 3)}", "绿柱缩短，下跌动能减弱"))
    rsi = lt["rsi14"]
    if rsi is not None:
        if rsi >= 80:
            sig = (-6, "严重超买，短期回调风险较大")
        elif rsi >= 70:
            sig = (-3, "进入超买区，追高需谨慎")
        elif rsi >= 50:
            sig = (4, "处于强势区间")
        elif rsi > 30:
            sig = (-4, "处于弱势区间")
        elif rsi > 20:
            sig = (3, "进入超卖区，存在技术性反弹可能")
        else:
            sig = (5, "严重超卖，反弹概率上升（但下跌趋势中可能持续超卖）")
        out.append(Signal("rsi", "RSI(14)", "momentum", sig[0], f"{rsi:.1f}", f"RSI {rsi:.1f}，{sig[1]}"))
    if tech["has_ohlc"]:
        kv, dv, jv = lt["k"], lt["d"], lt["j"]
        if None not in (kv, dv, jv):
            kcross = _cross(s["k"], s["d"], 3)
            if jv > 100:
                out.append(Signal("kdj", "KDJ", "momentum", -4, f"K {kv:.0f} D {dv:.0f} J {jv:.0f}", "J 值超过 100，短线超买"))
            elif jv < 0:
                out.append(Signal("kdj", "KDJ", "momentum", 4, f"K {kv:.0f} D {dv:.0f} J {jv:.0f}", "J 值低于 0，短线超卖"))
            elif kcross > 0 and kv < 35:
                out.append(Signal("kdj", "KDJ", "momentum", 5, f"K {kv:.0f} D {dv:.0f} J {jv:.0f}", "低位金叉，短线转强"))
            elif kcross < 0 and kv > 65:
                out.append(Signal("kdj", "KDJ", "momentum", -5, f"K {kv:.0f} D {dv:.0f} J {jv:.0f}", "高位死叉，短线转弱"))
    if tech["has_volume"] and lt.get("volume_ratio") is not None and len(bars) > 1:
        vr = lt["volume_ratio"]
        chg = bars[-1].close / bars[-2].close - 1
        if vr >= 1.8 and chg > 0.02:
            out.append(Signal("volume", "量价", "momentum", 5, f"量比 {vr:.2f}，涨 {chg * 100:.1f}%", "放量上涨，资金买入积极"))
        elif vr >= 1.8 and chg < -0.02:
            out.append(Signal("volume", "量价", "momentum", -6, f"量比 {vr:.2f}，跌 {abs(chg) * 100:.1f}%", "放量下跌，抛压较重"))
        elif vr <= 0.6:
            out.append(Signal("volume", "量价", "momentum", 0, f"量比 {vr:.2f}", "明显缩量，市场观望"))
    bu, bl = lt["boll_up"], lt["boll_low"]
    if bu and bl and bu > bl:
        pb = (close - bl) / (bu - bl)
        if pb > 1:
            out.append(Signal("boll", "布林带", "momentum", -3, f"%B {pb:.2f}", "收盘价突破布林上轨，短期偏离较大"))
        elif pb < 0:
            out.append(Signal("boll", "布林带", "momentum", 3, f"%B {pb:.2f}", "收盘价跌破布林下轨，短期超跌"))
    return out


def risk_signals(metrics_1y: dict) -> list[Signal]:
    """风险维度（分数越高 = 风险越低）。用近一年的波动、回撤、贝塔、VaR。"""
    out: list[Signal] = []
    if not metrics_1y:
        return out
    vol = metrics_1y.get("volatility")
    if vol is not None:
        impact = 10 if vol < 0.15 else 4 if vol < 0.25 else -4 if vol < 0.40 else -10
        level = "低" if vol < 0.15 else "中等" if vol < 0.25 else "较高" if vol < 0.40 else "很高"
        out.append(Signal("vol", "年化波动率", "risk", impact, f"{vol * 100:.1f}%", f"近一年年化波动率 {vol * 100:.1f}%，波动{level}"))
    mdd = metrics_1y.get("max_drawdown")
    if mdd is not None:
        impact = 8 if mdd > -0.10 else 3 if mdd > -0.20 else -4 if mdd > -0.35 else -10
        out.append(Signal("mdd", "最大回撤", "risk", impact, f"{mdd * 100:.1f}%",
                          f"近一年最大回撤 {mdd * 100:.1f}%（{metrics_1y.get('drawdown_peak')} → {metrics_1y.get('drawdown_trough')}）"))
    beta = metrics_1y.get("beta")
    if beta is not None:
        if beta > 1.3:
            out.append(Signal("beta", "贝塔", "risk", -4, f"{beta:.2f}", f"贝塔 {beta:.2f}，涨跌幅度明显大于基准"))
        elif beta < 0.7:
            out.append(Signal("beta", "贝塔", "risk", 3, f"{beta:.2f}", f"贝塔 {beta:.2f}，受大盘波动影响较小"))
        else:
            out.append(Signal("beta", "贝塔", "risk", 0, f"{beta:.2f}", f"贝塔 {beta:.2f}，与基准波动相当"))
    var95 = metrics_1y.get("var95")
    if var95 is not None and var95 > 0.04:
        out.append(Signal("var", "单日风险", "risk", -4, f"VaR95 {var95 * 100:.1f}%", f"历史上 5% 的交易日单日跌幅超过 {var95 * 100:.1f}%"))
    return out
