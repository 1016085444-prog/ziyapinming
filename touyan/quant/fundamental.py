"""股票基本面：估值、盈利质量、成长性。

两处容易算错、这里专门处理的口径：

1. **A 股季报的 ROE 是累计值**：一季报 ROE 只有全年的约 1/4，直接拿来打分会把每只
   股票的一季报都判成「盈利能力差」。这里按报告期年化（一季报×4、半年报×2、三季报×4/3）。
2. **金融企业不看负债率和毛利率**：银行负债率 90% 是正常经营，没有「毛利」概念。
   按行业识别后跳过这两项，并在依据里说明。

估值只做绝对水平判断，**没有做行业横向比较**——白酒 30 倍和银行 30 倍含义完全不同，
所以估值类依据都会注明这一点，避免把粗略判断说成定论。
"""

from __future__ import annotations

from market.models import FinancialPeriod, Instrument, Quote
from quant.technical import Signal

_FINANCIAL_WORDS = ("银行", "保险", "证券", "多元金融", "信托", "期货", "Bank", "Insurance")


def is_financial(industry: str) -> bool:
    return any(w in (industry or "") for w in _FINANCIAL_WORDS)


def annualize_roe(period: FinancialPeriod, inst: Instrument) -> float | None:
    if period.roe is None:
        return None
    if inst.market not in ("SH", "SZ", "BJ"):
        return period.roe
    month = int(period.report_date[5:7]) if len(period.report_date) >= 7 else 12
    factor = {3: 4.0, 6: 2.0, 9: 4 / 3}.get(month, 1.0)
    return period.roe * factor


def _band(value: float, bands: list[tuple[float, float]], default: float) -> float:
    """bands: [(下限, 分值), ...] 从高到低，value ≥ 下限即取对应分值。"""
    for floor, score in bands:
        if value >= floor:
            return score
    return default


def analyze(inst: Instrument, quote: Quote | None, periods: list[FinancialPeriod], industry: str = "") -> dict:
    out: dict = {"available": bool(periods) or bool(quote and (quote.pe or quote.pb)), "signals": []}
    sigs: list[Signal] = []
    financial = is_financial(industry)
    latest = periods[0] if periods else None
    roe_ann = annualize_roe(latest, inst) if latest else None
    growth = latest.net_profit_yoy if latest else None

    # ── 估值 ──
    pe = quote.pe if quote else None
    pb = quote.pb if quote else None
    note = "（仅看绝对水平，未做同行业比较）"
    if pe is not None:
        if pe < 0:
            sigs.append(Signal("pe", "市盈率", "valuation", -10, f"{pe:.1f}", "市盈率为负，公司处于亏损状态，估值无法用 PE 衡量"))
        else:
            impact = _band(-pe, [(-12, 10), (-20, 6), (-35, 0), (-60, -6)], -10)
            level = "很低" if pe < 12 else "偏低" if pe < 20 else "适中" if pe < 35 else "偏高" if pe < 60 else "很高"
            sigs.append(Signal("pe", "市盈率(动态)", "valuation", impact, f"{pe:.1f} 倍", f"动态市盈率 {pe:.1f} 倍，估值{level}{note}"))
    if pb is not None and pb > 0:
        impact = _band(-pb, [(-1, 6), (-2, 3), (-5, 0), (-10, -4)], -6)
        extra = "，股价低于每股净资产（破净）" if pb < 1 else ""
        sigs.append(Signal("pb", "市净率", "valuation", impact, f"{pb:.2f} 倍", f"市净率 {pb:.2f} 倍{extra}{note}"))
    if pe and pe > 0 and growth and growth > 0:
        peg = pe / growth
        impact = _band(-peg, [(-0.8, 8), (-1.5, 3), (-3, -3)], -6)
        sigs.append(Signal("peg", "PEG", "valuation", impact, f"{peg:.2f}",
                           f"PEG = 市盈率 {pe:.1f} ÷ 净利润增速 {growth:.1f}% = {peg:.2f}，"
                           + ("增速能支撑估值" if peg < 1 else "估值相对增速偏贵" if peg > 2 else "估值与增速大致匹配")))

    # ── 盈利质量 ──
    if latest:
        if roe_ann is not None:
            impact = _band(roe_ann, [(20, 12), (15, 8), (10, 3), (5, -4), (0, -10)], -12)
            annual_note = "（按报告期年化）" if roe_ann != latest.roe else ""
            level = "优秀" if roe_ann >= 20 else "良好" if roe_ann >= 15 else "一般" if roe_ann >= 10 else "偏弱" if roe_ann >= 5 else "很差"
            sigs.append(Signal("roe", "ROE", "quality", impact, f"{roe_ann:.1f}%",
                               f"{latest.report_name or latest.report_date} 净资产收益率 {roe_ann:.1f}%{annual_note}，盈利能力{level}"))
        if latest.gross_margin is not None and not financial:
            gm = latest.gross_margin
            impact = _band(gm, [(50, 6), (30, 3), (15, 0)], -4)
            sigs.append(Signal("gm", "毛利率", "quality", impact, f"{gm:.1f}%",
                               f"毛利率 {gm:.1f}%，" + ("产品议价能力强" if gm >= 50 else "竞争力尚可" if gm >= 30 else "利润空间较薄" if gm >= 15 else "毛利很低，抗风险能力弱")))
        if latest.net_margin is not None:
            nm = latest.net_margin
            impact = _band(nm, [(20, 5), (10, 2), (0, 0)], -8)
            sigs.append(Signal("nm", "净利率", "quality", impact, f"{nm:.1f}%", f"净利率 {nm:.1f}%" + ("，处于亏损" if nm < 0 else "")))
        if latest.debt_ratio is not None:
            dr = latest.debt_ratio
            if financial:
                sigs.append(Signal("debt", "资产负债率", "quality", 0, f"{dr:.1f}%", f"资产负债率 {dr:.1f}%（金融企业高负债属正常经营特征，不计分）"))
            else:
                impact = _band(-dr, [(-30, 5), (-50, 2), (-70, -2), (-85, -6)], -10)
                sigs.append(Signal("debt", "资产负债率", "quality", impact, f"{dr:.1f}%",
                                   f"资产负债率 {dr:.1f}%，" + ("财务稳健" if dr < 50 else "负债偏高" if dr < 70 else "负债率高，需关注偿债压力")))
        if latest.ocf_per_share is not None and latest.eps:
            if latest.eps > 0:
                ratio = latest.ocf_per_share / latest.eps
                if latest.ocf_per_share < 0:
                    sigs.append(Signal("cash", "现金流质量", "quality", -8, f"每股经营现金流 {latest.ocf_per_share:.2f}",
                                       "经营现金流为负，利润没有转化为现金"))
                else:
                    impact = 5 if ratio >= 1 else 0 if ratio >= 0.5 else -5
                    sigs.append(Signal("cash", "现金流质量", "quality", impact, f"现金流/利润 {ratio:.2f}",
                                       f"每股经营现金流是每股收益的 {ratio:.2f} 倍，" + ("利润含金量高" if ratio >= 1 else "利润含金量一般" if ratio >= 0.5 else "利润含金量低")))

    # ── 成长 ──
    if latest:
        if latest.revenue_yoy is not None:
            g = latest.revenue_yoy
            impact = _band(g, [(30, 10), (15, 6), (5, 2), (0, -2), (-20, -8)], -12)
            sigs.append(Signal("rev", "营收增速", "growth", impact, f"{g:+.1f}%", f"营业收入同比{'增长' if g >= 0 else '下降'} {abs(g):.1f}%"))
        if latest.net_profit_yoy is not None:
            g = latest.net_profit_yoy
            impact = _band(g, [(30, 10), (15, 6), (5, 2), (0, -2), (-30, -8)], -12)
            sigs.append(Signal("np", "净利润增速", "growth", impact, f"{g:+.1f}%", f"归母净利润同比{'增长' if g >= 0 else '下降'} {abs(g):.1f}%"))
        if latest.deduct_profit_yoy is not None and latest.net_profit_yoy is not None:
            if (latest.deduct_profit_yoy >= 0) != (latest.net_profit_yoy >= 0):
                sigs.append(Signal("deduct", "扣非净利润", "growth", -3, f"{latest.deduct_profit_yoy:+.1f}%",
                                   f"扣非净利润同比 {latest.deduct_profit_yoy:+.1f}%，与归母净利润方向相反，利润受非经常性损益影响较大"))
        prev = periods[1] if len(periods) > 1 else None
        if prev and latest.revenue_yoy is not None and prev.revenue_yoy is not None:
            delta = latest.revenue_yoy - prev.revenue_yoy
            if abs(delta) >= 5:
                sigs.append(Signal("rev_trend", "增速变化", "growth", 3 if delta > 0 else -3, f"{delta:+.1f} 个百分点",
                                   f"营收增速较上一期{'加快' if delta > 0 else '放缓'} {abs(delta):.1f} 个百分点"))

    out["signals"] = sigs
    out["valuation"] = {
        "pe": pe, "pb": pb,
        "peg": (pe / growth) if (pe and pe > 0 and growth and growth > 0) else None,
        "total_cap": quote.total_cap if quote else None,
        "float_cap": quote.float_cap if quote else None,
    }
    out["is_financial"] = financial
    out["latest"] = None if latest is None else {**latest.__dict__, "roe_annualized": roe_ann}
    out["history"] = [
        {"report_date": p.report_date, "report_name": p.report_name, "revenue": p.revenue,
         "revenue_yoy": p.revenue_yoy, "net_profit": p.net_profit, "net_profit_yoy": p.net_profit_yoy,
         "roe": annualize_roe(p, inst), "gross_margin": p.gross_margin, "debt_ratio": p.debt_ratio}
        for p in periods[:8]
    ]
    return out
