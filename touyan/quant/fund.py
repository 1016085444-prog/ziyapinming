"""基金专项：业绩、回撤控制、性价比、稳定性（经理、规模、持仓）。

场外基金和 ETF 共用。ETF 的核心是「跟得准、规模够、流动性好」，所以 ETF 只用
稳定性维度里的规模项；主动基金看的东西更多。

两条要明确告诉用户的事实：
- **规模过小有清盘风险**：开放式基金资产净值连续 60 个工作日低于 5000 万元，
  基金合同可能终止（《公开募集证券投资基金运作管理办法》）。
- **新任基金经理的历史业绩不是他的**：经理任职不满一年时，净值走势主要反映前任。
"""

from __future__ import annotations

from market.models import FundProfile, Instrument
from quant.technical import Signal


def analyze(inst: Instrument, profile: FundProfile | None, windows: dict, returns: dict,
            bench_name: str = "沪深300") -> dict:
    sigs: list[Signal] = []
    m1 = windows.get("1y", {})
    m3 = windows.get("3y", {})
    active = inst.market == "OF"

    # ── 业绩 ──
    if active:
        excess = m1.get("excess_return")
        if excess is not None:
            impact = 10 if excess > 0.10 else 5 if excess > 0.03 else -10 if excess < -0.10 else -5 if excess < -0.03 else 0
            sigs.append(Signal("excess", "相对基准", "performance", impact, f"{excess * 100:+.1f}%",
                               f"近一年{'跑赢' if excess >= 0 else '跑输'}{bench_name} {abs(excess) * 100:.1f} 个百分点"))
        if profile and profile.rank_beat_pct is not None:
            beat = profile.rank_beat_pct
            impact = 8 if beat >= 80 else 4 if beat >= 60 else 0 if beat >= 40 else -4 if beat >= 20 else -8
            sigs.append(Signal("rank", "同类排名", "performance", impact, f"{profile.rank}/{profile.rank_total}",
                               f"近三月同类排名 {profile.rank}/{profile.rank_total}，超过 {beat:.0f}% 的同类基金"))
        cagr3 = m3.get("cagr")
        if cagr3 is not None:
            impact = 6 if cagr3 > 0.15 else 3 if cagr3 > 0.08 else -6 if cagr3 < 0 else 0
            sigs.append(Signal("cagr3", "三年年化", "performance", impact, f"{cagr3 * 100:+.1f}%", f"近三年年化收益 {cagr3 * 100:+.1f}%"))
        elif returns.get("1y") is not None:
            r1 = returns["1y"]
            impact = 6 if r1 > 0.20 else 3 if r1 > 0.08 else -6 if r1 < -0.10 else -2 if r1 < 0 else 0
            sigs.append(Signal("ret1y", "近一年收益", "performance", impact, f"{r1 * 100:+.1f}%", f"近一年收益 {r1 * 100:+.1f}%"))

    # ── 回撤控制 ──
    if active and m1:
        mdd = m1.get("max_drawdown")
        if mdd is not None:
            impact = 5 if mdd > -0.10 else 0 if mdd > -0.20 else -3 if mdd > -0.30 else -6
            sigs.append(Signal("fmdd", "最大回撤", "risk_control", impact, f"{mdd * 100:.1f}%", f"近一年最大回撤 {mdd * 100:.1f}%"))
        vol = m1.get("volatility")
        if vol is not None:
            impact = 5 if vol < 0.10 else 2 if vol < 0.20 else -2 if vol < 0.30 else -5
            sigs.append(Signal("fvol", "波动率", "risk_control", impact, f"{vol * 100:.1f}%", f"近一年年化波动率 {vol * 100:.1f}%"))

    # ── 性价比 ──
    if active:
        s1 = m1.get("sharpe")
        if s1 is not None:
            impact = 12 if s1 > 1.5 else 8 if s1 > 1 else 3 if s1 > 0.5 else -3 if s1 > 0 else -10
            sigs.append(Signal("sharpe1", "夏普比率(1年)", "efficiency", impact, f"{s1:.2f}",
                               f"近一年夏普比率 {s1:.2f}，每承担一份波动换来的超额收益" + ("很高" if s1 > 1.5 else "较高" if s1 > 1 else "一般" if s1 > 0.5 else "偏低" if s1 > 0 else "为负")))
        s3 = m3.get("sharpe")
        if s3 is not None:
            impact = 6 if s3 > 1 else 3 if s3 > 0.5 else -2 if s3 > 0 else -6
            sigs.append(Signal("sharpe3", "夏普比率(3年)", "efficiency", impact, f"{s3:.2f}", f"近三年夏普比率 {s3:.2f}"))
        calmar = m1.get("calmar")
        if calmar is not None:
            if calmar > 2:
                sigs.append(Signal("calmar", "卡玛比率", "efficiency", 5, f"{calmar:.2f}", f"卡玛比率 {calmar:.2f}，收益对回撤的补偿充分"))
            elif calmar < 0.3:
                sigs.append(Signal("calmar", "卡玛比率", "efficiency", -3, f"{calmar:.2f}", f"卡玛比率 {calmar:.2f}，收益难以补偿回撤"))

    # ── 稳定性：经理、规模、持仓 ──
    if profile:
        tenures = [m.tenure_years for m in profile.managers if m.tenure_years is not None]
        if active and tenures:
            t = max(tenures)
            names = "、".join(m.name for m in profile.managers)
            impact = 8 if t >= 5 else 5 if t >= 3 else 0 if t >= 1 else -6
            detail = f"现任基金经理 {names}，最长任职 {t:.1f} 年"
            if t < 1:
                detail += "；任职不满一年，此前的净值表现主要不是现任经理的业绩"
            sigs.append(Signal("manager", "基金经理", "stability", impact, f"{t:.1f} 年", detail))
        if profile.scale is not None:
            sc = profile.scale
            if sc < 0.5:
                sigs.append(Signal("scale", "基金规模", "stability", -12, f"{sc:.2f} 亿",
                                   f"规模仅 {sc:.2f} 亿元，低于 5000 万元并持续 60 个工作日可能触发清盘"))
            elif sc < 2:
                sigs.append(Signal("scale", "基金规模", "stability", -5, f"{sc:.2f} 亿", f"规模 {sc:.2f} 亿元，偏小" + ("，ETF 流动性可能不足" if not active else "")))
            elif not active and sc >= 50:
                sigs.append(Signal("scale", "基金规模", "stability", 5, f"{sc:.1f} 亿", f"规模 {sc:.1f} 亿元，流动性充足"))
            elif active and sc > 100:
                sigs.append(Signal("scale", "基金规模", "stability", 0, f"{sc:.1f} 亿", f"规模 {sc:.1f} 亿元，规模较大，主动管理调仓难度上升"))
            else:
                sigs.append(Signal("scale", "基金规模", "stability", 3, f"{sc:.1f} 亿", f"规模 {sc:.1f} 亿元，适中"))
        weights = [h.weight for h in profile.holdings if h.weight is not None]
        if active and len(weights) >= 5:
            top = sum(weights)
            if top > 70:
                sigs.append(Signal("concentration", "持仓集中度", "stability", -3, f"前十大 {top:.1f}%",
                                   f"前十大重仓股合计占净值 {top:.1f}%，持仓高度集中，个股风险对净值影响大"))
            else:
                sigs.append(Signal("concentration", "持仓集中度", "stability", 0, f"前十大 {top:.1f}%", f"前十大重仓股合计占净值 {top:.1f}%"))

    out = {"signals": sigs, "available": profile is not None}
    if profile:
        out["profile"] = {
            "name": profile.name, "fund_type": profile.fund_type, "establish_date": profile.establish_date,
            "company": profile.company, "custodian": profile.custodian, "benchmark": profile.benchmark,
            "strategy": profile.strategy, "scale": profile.scale, "scale_date": profile.scale_date,
            "fee_rate": profile.fee_rate, "fee_rate_original": profile.fee_rate_original,
            "managers": [m.__dict__ for m in profile.managers],
            "returns": profile.returns, "rank": profile.rank, "rank_total": profile.rank_total,
            "rank_beat_pct": profile.rank_beat_pct, "stock_ratio": profile.stock_ratio,
            "allocation": profile.allocation, "allocation_date": profile.allocation_date,
            "holdings": [h.__dict__ for h in profile.holdings], "holdings_period": profile.holdings_period,
            "evaluation": profile.evaluation,
        }
    return out
