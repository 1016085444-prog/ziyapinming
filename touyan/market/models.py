"""行情数据的统一结构。

所有数据源（东方财富、腾讯、CSV 导入、可选的 akshare / yfinance）都先转换成
这里的类型，分析层和智能体只认这些——换数据源不必动分析代码。

数值一律是 float 或 None：**None 表示「没取到」，绝不用 0 冒充。**
市盈率 0 和市盈率未知在投资分析里是两回事，混用会让下游得出错误结论。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

KIND_LABELS = {
    "stock": "股票",
    "etf": "场内基金",
    "fund": "场外基金",
    "index": "指数",
}

MARKET_LABELS = {
    "SH": "沪市",
    "SZ": "深市",
    "BJ": "北交所",
    "HK": "港股",
    "US": "美股",
    "OF": "场外基金",
    "GI": "全球指数",
    "CSV": "导入数据",
}

CURRENCY_LABELS = {"CNY": "元", "HKD": "港元", "USD": "美元"}


@dataclass
class Instrument:
    """一只证券/基金/指数的身份。

    code 是规范代码（600519 / 00700 / AAPL / 110011 / HSI），market + code 唯一确定一个品种。
    secid 是东方财富的行情 ID（如 1.600519），美股在解析阶段不知道交易所时为空，
    由路由层通过搜索或逐个尝试补全。
    """

    code: str
    market: str
    kind: str
    name: str = ""
    secid: str = ""
    currency: str = "CNY"

    @property
    def key(self) -> str:
        """URL、历史记录里用的唯一键，如 SH:600519。"""
        return f"{self.market}:{self.code}"

    @property
    def display(self) -> str:
        return f"{self.name}（{self.code}）" if self.name else self.code

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def market_label(self) -> str:
        return MARKET_LABELS.get(self.market, self.market)

    @property
    def is_fund_like(self) -> bool:
        """ETF/LOF 本质也是基金，有基金经理、规模、持仓。"""
        return self.kind in ("fund", "etf")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.update(key=self.key, kind_label=self.kind_label, market_label=self.market_label)
        return d


@dataclass
class Bar:
    """一根日线。场外基金的 o/h/l/c 都是单位净值。

    adj 是用于计算收益的复权价：股票取前复权数据时它就等于 close（留 None）；
    基金按每日「净值回报」连乘得到，分红再投资后的真实收益才对得上。
    """

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float | None = None
    turnover: float | None = None
    adj: float | None = None

    @property
    def adj_close(self) -> float:
        return self.adj if self.adj is not None else self.close


@dataclass
class Quote:
    """实时（或最近）行情快照与估值。字段取不到就是 None。"""

    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    prev_close: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover: float | None = None
    pe: float | None = None          # 东方财富「市盈率-动态」
    pb: float | None = None
    total_cap: float | None = None   # 总市值（元）
    float_cap: float | None = None   # 流通市值（元）
    change_60d: float | None = None
    change_ytd: float | None = None
    industry: str = ""
    time: str = ""
    source: str = ""


@dataclass
class FinancialPeriod:
    """一个报告期的主要财务指标。比率类字段单位为 %。"""

    report_date: str
    report_name: str = ""
    revenue: float | None = None
    revenue_yoy: float | None = None
    net_profit: float | None = None
    net_profit_yoy: float | None = None
    deduct_profit_yoy: float | None = None
    roe: float | None = None
    gross_margin: float | None = None
    net_margin: float | None = None
    debt_ratio: float | None = None
    eps: float | None = None
    bps: float | None = None
    ocf_per_share: float | None = None
    current_ratio: float | None = None


@dataclass
class FundManager:
    name: str
    tenure: str = ""                 # 原文，如「6年又200天」
    tenure_years: float | None = None
    managed_size: str = ""           # 原文，如「123.45亿(5只基金)」


@dataclass
class Holding:
    code: str
    name: str
    weight: float | None = None      # 占净值比例 %


@dataclass
class FundProfile:
    """基金档案。场外基金与 ETF 共用。"""

    name: str = ""
    fund_type: str = ""
    establish_date: str = ""
    company: str = ""
    custodian: str = ""
    benchmark: str = ""
    strategy: str = ""
    managers: list[FundManager] = field(default_factory=list)
    scale: float | None = None       # 规模（亿元）
    scale_date: str = ""
    fee_rate: float | None = None    # 当前申购费率 %
    fee_rate_original: float | None = None
    returns: dict[str, float] = field(default_factory=dict)   # 1m/3m/6m/1y，单位 %
    rank: int | None = None          # 近三月同类排名
    rank_total: int | None = None
    stock_ratio: float | None = None  # 股票仓位 %
    allocation: dict[str, float] = field(default_factory=dict)  # 最新一期资产配置 %
    allocation_date: str = ""
    holdings: list[Holding] = field(default_factory=list)
    holdings_period: str = ""
    evaluation: dict[str, float] = field(default_factory=dict)  # 选证能力/收益率/抗风险...
    source: str = ""

    @property
    def rank_beat_pct(self) -> float | None:
        """超过多少比例的同类（0–100）。排名 1/100 → 100%，100/100 → 1%。"""
        if not self.rank or not self.rank_total or self.rank_total <= 1:
            return None
        return round((1 - (self.rank - 1) / self.rank_total) * 100, 1)


@dataclass
class NewsItem:
    title: str
    time: str = ""
    source: str = ""
    url: str = ""
    summary: str = ""


@dataclass
class MarketData:
    """一次分析需要的全部原始数据，以及每块数据来自哪里、哪些没取到。"""

    instrument: Instrument
    bars: list[Bar]
    benchmark: Instrument | None = None
    benchmark_bars: list[Bar] = field(default_factory=list)
    quote: Quote | None = None
    financials: list[FinancialPeriod] = field(default_factory=list)
    fund: FundProfile | None = None
    news: list[NewsItem] = field(default_factory=list)
    market_news: list[NewsItem] = field(default_factory=list)
    company: dict[str, str] = field(default_factory=dict)   # 行业、简介等
    sources: dict[str, str] = field(default_factory=dict)   # 数据块 → 数据源
    warnings: list[str] = field(default_factory=list)       # 中文，直接给用户看
    fetched_at: str = ""
    volume_unit: str = "手"

    @property
    def last_bar(self) -> Bar | None:
        return self.bars[-1] if self.bars else None
