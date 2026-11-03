"""数据路由：按品种选数据源链，失败自动降级，结果进缓存。

学自 TradingAgents 的 dataflows/router：每类数据配置一条「数据源链」，前一个失败就试
下一个，并把每块数据实际来自哪里记下来，报告里如实标注。

几条原则：
- **能降级就降级，不能降级就说清楚。** 所有源都失败时，用最近一次缓存兜底并明确标注
  「这是 X 小时前的数据」；连缓存都没有才报错，报错要说清是哪些源、为什么失败。
- **分散东方财富 push2 的请求。** 它会因密集请求封 IP（见 net.py），所以基准指数的
  K 线优先走腾讯，个股行情才走东方财富。
- **辅助数据失败不拖垮主流程。** 新闻、财务取不到只记一条提示，分析照常进行。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime

from market import eastmoney, fundem, news, optional, symbols, tencent
from market.cache import Cache, humanize_age
from market.models import (
    Bar, FinancialPeriod, FundManager, FundProfile, Holding, Instrument, MarketData, NewsItem, Quote,
)
from market.net import NoData, SourceError

TTL = {
    "kline": 15 * 60,
    "quote": 60,
    "fund": 6 * 3600,
    "fin": 12 * 3600,
    "news": 30 * 60,
    "mnews": 10 * 60,
    "search": 86400,
    "profile": 7 * 86400,
    "secid": 30 * 86400,
}

VENDOR_LABELS = {
    "eastmoney": "东方财富", "tencent": "腾讯证券", "akshare": "akshare", "yfinance": "Yahoo(yfinance)",
    "tiantian": "天天基金", "danjuan": "蛋卷基金", "sina": "新浪财经", "csv": "导入的 CSV",
}

DEFAULT_KLINE_VENDORS = ["eastmoney", "tencent", "akshare", "yfinance"]
BENCHMARK_VENDORS = ["tencent", "eastmoney", "akshare", "yfinance"]


# ── 缓存序列化 ─────────────────────────────────────────────────

def bars_to_rows(bars: list[Bar]) -> list[list]:
    return [[b.date, b.open, b.high, b.low, b.close, b.volume, b.amount, b.turnover, b.adj] for b in bars]


def rows_to_bars(rows: list[list]) -> list[Bar]:
    return [Bar(*r) for r in rows]


def profile_from_dict(d: dict) -> FundProfile:
    d = dict(d)
    d["managers"] = [FundManager(**m) for m in d.get("managers", [])]
    d["holdings"] = [Holding(**h) for h in d.get("holdings", [])]
    return FundProfile(**d)


class DataRouter:
    def __init__(self, cache: Cache, kline_vendors: list[str] | None = None):
        self.cache = cache
        env = os.environ.get("TOUYAN_KLINE_VENDORS", "")
        self.kline_vendors = kline_vendors or [v.strip() for v in env.split(",") if v.strip()] or DEFAULT_KLINE_VENDORS
        self._optional = optional.available()

    # ── 搜索与解析 ──────────────────────────────────────────────

    def search(self, text: str, limit: int = 10) -> list[Instrument]:
        """代码规则解析（离线可用）+ 东方财富搜索 + 天天基金搜索，合并去重。"""
        text = (text or "").strip()[:40]
        if not text:
            return []
        offline = symbols.alternatives(text)
        online: list[Instrument] = []
        key = f"search:{text.lower()}"
        cached = self.cache.get(key, TTL["search"])
        if cached is not None:
            online = [Instrument(**d) for d in cached]
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(eastmoney.search, text), pool.submit(fundem.search, text)]
                got_any = False
                for fut in futures:
                    try:
                        online.extend(fut.result())
                        got_any = True
                    except SourceError:
                        continue
            if got_any:
                self.cache.set(key, [asdict(i) for i in online])
        merged: dict[str, Instrument] = {}
        for inst in online + offline:
            if inst.key not in merged:
                merged[inst.key] = inst
            elif not merged[inst.key].name and inst.name:
                merged[inst.key].name = inst.name
        # 输入恰好是代码时，代码完全匹配的排前面
        upper = text.upper()
        ordered = sorted(merged.values(), key=lambda i: (i.code.upper() != upper and i.code.upper().lstrip("0") != upper.lstrip("0")))
        return ordered[:limit]

    def resolve(self, text: str, kind: str = "auto") -> Instrument:
        inst = symbols.parse(text, kind)
        if inst is not None:
            return inst
        hits = self.search(text)
        if not hits:
            raise NoData(f"找不到「{text}」。请输入代码（如 600519、00700、AAPL、510300、110011），或检查网络后用名称搜索")
        return hits[0]

    # ── K 线 ────────────────────────────────────────────────────

    def _us_secids(self, inst: Instrument) -> list[str]:
        if inst.secid:
            return [inst.secid]
        cached = self.cache.get(f"secid:{inst.key}", TTL["secid"])
        if cached:
            return [cached]
        try:
            for hit in eastmoney.search(inst.code, count=5):
                if hit.market == "US" and hit.code.upper() == inst.code.upper() and hit.secid:
                    self.cache.set(f"secid:{inst.key}", hit.secid)
                    return [hit.secid]
        except SourceError:
            pass
        return symbols.us_secid_candidates(inst.code)

    def _kline_from(self, vendor: str, inst: Instrument, days: int) -> tuple[list[Bar], str]:
        if vendor == "eastmoney":
            secids = self._us_secids(inst) if inst.market == "US" else [symbols.em_secid(inst)]
            last: Exception | None = None
            for secid in secids:
                if not secid:
                    continue
                try:
                    name, bars = eastmoney.kline(secid, days)
                except NoData as exc:
                    last = exc
                    continue
                if inst.market == "US":
                    inst.secid = secid
                    self.cache.set(f"secid:{inst.key}", secid)
                return bars, name
            raise last or NoData("东方财富不支持该品种")
        if vendor == "tencent":
            sym = symbols.tencent_symbol(inst)
            if not sym or inst.market == "US":
                raise NoData("腾讯行情不支持该品种")
            return tencent.kline(sym, days), ""
        if vendor == "akshare":
            return optional.akshare_kline(inst, days), ""
        if vendor == "yfinance":
            return optional.yfinance_kline(inst, days), ""
        raise NoData(f"未知数据源 {vendor}")

    def bars(self, inst: Instrument, days: int = 800, vendors: list[str] | None = None) -> tuple[list[Bar], str, str]:
        """返回 (K 线, 数据源说明, 名称)。全部失败时用旧缓存兜底，并在数据源说明里写明。"""
        key = f"kline:{inst.key}:{days}"
        hit = self.cache.get(key, TTL["kline"])
        if hit:
            return rows_to_bars(hit["rows"]), hit["source"], hit.get("name", "")
        errors: list[str] = []
        for vendor in vendors or self.kline_vendors:
            if vendor in self._optional and not self._optional[vendor]:
                continue
            try:
                bars, name = self._kline_from(vendor, inst, days)
            except SourceError as exc:
                errors.append(f"{VENDOR_LABELS.get(vendor, vendor)}：{exc}")
                continue
            if bars:
                source = VENDOR_LABELS.get(vendor, vendor)
                self.cache.set(key, {"rows": bars_to_rows(bars), "source": source, "name": name})
                return bars, source, name
        stale = self.cache.get_stale(key)
        if stale:
            data, age = stale
            return rows_to_bars(data["rows"]), f"{data['source']}（{humanize_age(age)}前的缓存，实时数据获取失败）", data.get("name", "")
        raise SourceError("所有数据源都没有取到行情：" + "；".join(errors or ["没有可用的数据源"]))

    # ── 行情快照 ────────────────────────────────────────────────

    def quote(self, inst: Instrument) -> tuple[Quote, str]:
        key = f"quote:{inst.key}"
        hit = self.cache.get(key, TTL["quote"])
        if hit:
            return Quote(**hit["quote"]), hit.get("name", "")
        errors = []
        secid = symbols.em_secid(inst) or (self._us_secids(inst)[0] if inst.market == "US" else "")
        if secid:
            try:
                name, q = eastmoney.quote(secid)
                self.cache.set(key, {"quote": asdict(q), "name": name})
                return q, name
            except SourceError as exc:
                errors.append(f"东方财富：{exc}")
        sym = symbols.tencent_symbol(inst)
        if sym:
            try:
                name, q = tencent.quote(sym)
                self.cache.set(key, {"quote": asdict(q), "name": name})
                return q, name
            except SourceError as exc:
                errors.append(f"腾讯证券：{exc}")
        raise SourceError("行情快照获取失败：" + "；".join(errors or ["该品种没有快照数据源"]))

    # ── 基金 ────────────────────────────────────────────────────

    def fund(self, inst: Instrument) -> tuple[FundProfile, list[Bar], list[str]]:
        """基金档案 + 净值序列。warnings 里是非致命的缺项说明。"""
        key = f"fund:{inst.code}"
        hit = self.cache.get(key, TTL["fund"])
        if hit:
            return profile_from_dict(hit["profile"]), rows_to_bars(hit["rows"]), hit.get("warnings", [])
        warnings: list[str] = []
        try:
            profile, bars, top_secids = fundem.pingzhong(inst.code)
        except SourceError:
            stale = self.cache.get_stale(key)
            if stale:
                data, age = stale
                return (profile_from_dict(data["profile"]), rows_to_bars(data["rows"]),
                        data.get("warnings", []) + [f"基金数据为 {humanize_age(age)}前的缓存（天天基金暂时无法访问）"])
            raise
        try:
            fundem.merge_danjuan(profile, fundem.danjuan(inst.code))
        except SourceError as exc:
            warnings.append(f"基金类型/基准等档案未取到（蛋卷基金：{exc}）")
        try:
            period, holdings = fundem.holdings(inst.code)
            if holdings:
                profile.holdings, profile.holdings_period = holdings, period
        except SourceError:
            pass
        if not profile.holdings and top_secids:
            try:
                info = eastmoney.names(top_secids)
                profile.holdings = [Holding(code=s.split(".", 1)[1], name=info.get(s.split(".", 1)[1], ("", None))[0])
                                    for s in top_secids]
            except SourceError:
                profile.holdings = [Holding(code=s.split(".", 1)[1], name="") for s in top_secids]
        self.cache.set(key, {"profile": asdict(profile), "rows": bars_to_rows(bars), "warnings": warnings})
        return profile, bars, warnings

    # ── 财务、档案、新闻 ────────────────────────────────────────

    def company(self, inst: Instrument) -> dict[str, str]:
        if inst.market != "US":
            return {}
        key = f"profile:{inst.key}"
        hit = self.cache.get(key, TTL["profile"])
        if hit is not None:
            return hit
        info = eastmoney.us_profile(inst.code)
        self.cache.set(key, info)
        return info

    def financials(self, inst: Instrument) -> list[FinancialPeriod]:
        key = f"fin:{inst.key}"
        hit = self.cache.get(key, TTL["fin"])
        if hit is not None:
            return [FinancialPeriod(**d) for d in hit]
        secucode = self.company(inst).get("secucode", "") if inst.market == "US" else ""
        periods = eastmoney.financials(inst, us_secucode=secucode)
        self.cache.set(key, [asdict(p) for p in periods])
        return periods

    def company_news(self, keyword: str) -> list[NewsItem]:
        key = f"news:{keyword}"
        hit = self.cache.get(key, TTL["news"])
        if hit is not None:
            return [NewsItem(**d) for d in hit]
        items = news.company_news(keyword)
        self.cache.set(key, [asdict(n) for n in items])
        return items

    def market_news(self) -> tuple[list[NewsItem], str]:
        hit = self.cache.get("mnews", TTL["mnews"])
        if hit is not None:
            return [NewsItem(**d) for d in hit["items"]], hit["source"]
        errors = []
        for label, fetch in (("东方财富7x24", news.market_news), ("新浪财经7x24", news.sina_market_news)):
            try:
                items = fetch()
            except SourceError as exc:
                errors.append(f"{label}：{exc}")
                continue
            if items:
                self.cache.set("mnews", {"items": [asdict(n) for n in items], "source": label})
                return items, label
        raise SourceError("市场快讯获取失败：" + "；".join(errors))

    # ── 汇总 ────────────────────────────────────────────────────

    def load(self, inst: Instrument, days: int = 800, with_news: bool = True) -> MarketData:
        """取齐一次分析需要的全部数据。主行情取不到才抛异常，其余缺项记入 warnings。"""
        md = MarketData(instrument=inst, bars=[], fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        md.volume_unit = "手" if inst.market in ("SH", "SZ", "BJ") else "股"
        cn_fund = inst.market == "OF" or (inst.kind == "etf" and inst.market in ("SH", "SZ"))
        bench = symbols.benchmark_for(inst)
        md.benchmark = bench

        def price_bundle():
            bars, source, name = self.bars(inst, days)
            try:
                q, qname = self.quote(inst)
            except SourceError as exc:
                return bars, source, name, None, str(exc)
            return bars, source, name or qname, q, ""

        with ThreadPoolExecutor(max_workers=6) as pool:
            f_price = pool.submit(price_bundle) if inst.market != "OF" else None
            f_fund = pool.submit(self.fund, inst) if cn_fund else None
            f_bench = pool.submit(self.bars, bench, days, BENCHMARK_VENDORS) if bench.key != inst.key else None
            f_fin = pool.submit(self.financials, inst) if inst.kind == "stock" else None
            f_company = pool.submit(self.company, inst) if inst.market == "US" else None
            f_mnews = pool.submit(self.market_news) if with_news else None
            want_company_news = with_news and inst.kind == "stock"
            f_news = pool.submit(self.company_news, inst.code) if want_company_news and inst.market in ("SH", "SZ", "BJ") else None

            if f_fund is not None:
                try:
                    md.fund, nav, fund_warnings = f_fund.result()
                    md.warnings.extend(fund_warnings)
                    md.sources["基金档案"] = "天天基金 / 蛋卷基金"
                    if inst.market == "OF":
                        md.bars = nav
                        md.sources["净值"] = "天天基金"
                        inst.name = inst.name or md.fund.name
                except SourceError as exc:
                    if inst.market == "OF":
                        raise
                    md.warnings.append(f"基金档案未取到：{exc}")
            if f_price is not None:
                bars, source, name, q, qerr = f_price.result()   # 主行情失败直接抛出
                md.bars, md.quote = bars, q
                md.sources["行情"] = source
                if q is not None:
                    md.sources["快照"] = q.source
                elif qerr:
                    md.warnings.append(f"实时快照未取到，价格以最新 K 线收盘为准（{qerr}）")
                inst.name = inst.name or name
            if f_bench is not None:
                try:
                    md.benchmark_bars, bsource, _ = f_bench.result()
                    md.sources["基准"] = f"{bench.name}（{bsource}）"
                except SourceError as exc:
                    md.warnings.append(f"基准指数 {bench.name} 未取到，相对收益与贝塔无法计算（{exc}）")
            else:
                md.benchmark_bars = md.bars
            if f_company is not None:
                try:
                    md.company = f_company.result()
                    inst.name = inst.name or md.company.get("name", "")
                except SourceError as exc:
                    md.warnings.append(f"公司档案未取到：{exc}")
            if f_fin is not None:
                try:
                    md.financials = f_fin.result()
                    md.sources["财务"] = "东方财富"
                except SourceError as exc:
                    md.warnings.append(f"财务数据未取到，基本面分析将不完整（{exc}）")
            if f_mnews is not None:
                try:
                    md.market_news, msource = f_mnews.result()
                    md.sources["市场快讯"] = msource
                except SourceError as exc:
                    md.warnings.append(f"市场快讯未取到：{exc}")
            # 港股、美股按名称搜新闻，名称要等行情取回来才知道
            if want_company_news and f_news is None and inst.name:
                f_news = pool.submit(self.company_news, inst.name)
            if f_news is not None:
                try:
                    md.news = f_news.result()
                    md.sources["个股新闻"] = "东方财富"
                except SourceError as exc:
                    md.warnings.append(f"个股新闻未取到：{exc}")

        if md.quote and md.quote.industry:
            md.company.setdefault("industry", md.quote.industry)
        if len(md.bars) < 30:
            raise NoData(f"{inst.display} 的历史数据只有 {len(md.bars)} 条，不足以分析（至少需要 30 个交易日）")
        return md

    def load_csv(self, name: str, bars: list[Bar], currency: str = "CNY", with_benchmark: bool = True) -> MarketData:
        inst = Instrument(code="CSV", market="CSV", kind="fund" if all(b.open == b.close for b in bars) else "stock",
                          name=name or "导入数据", currency=currency)
        md = MarketData(instrument=inst, bars=bars, fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M"))
        md.sources["行情"] = VENDOR_LABELS["csv"]
        md.volume_unit = ""
        bench = symbols.benchmark_for(Instrument("X", {"HKD": "HK", "USD": "US"}.get(currency, "SH"), "stock"))
        md.benchmark = bench
        if with_benchmark:
            try:
                md.benchmark_bars, bsource, _ = self.bars(bench, max(800, len(bars)), BENCHMARK_VENDORS)
                md.sources["基准"] = f"{bench.name}（{bsource}）"
            except SourceError as exc:
                md.warnings.append(f"基准指数 {bench.name} 未取到，相对收益与贝塔无法计算（{exc}）")
        return md

    def series(self, inst: Instrument, days: int = 800) -> tuple[list[Bar], str]:
        """只取价格序列（多品种对比、复盘用）。A 股 / 港股优先走腾讯，少占东方财富 push2 的额度。"""
        if inst.market == "OF":
            profile, bars, _ = self.fund(inst)
            inst.name = inst.name or profile.name
            return bars, "天天基金"
        bars, source, name = self.bars(inst, days, BENCHMARK_VENDORS)
        inst.name = inst.name or name
        return bars, source
