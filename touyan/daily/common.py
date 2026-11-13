"""四个板块共用的小工具：取值范围、分位排名、股票筛除规则、行业大类与分散。"""

from __future__ import annotations

import math
import re

ST_RE = re.compile(r"ST|退")
NEW_RE = re.compile(r"^[NC][一-鿿]")      # 上市首日 N、注册制前 5 日 C


def clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def price(x: float | None) -> float | None:
    if x is None:
        return None
    return round(x, 3 if x < 1 else 2)


def pct(x: float | None, digits: int = 1) -> float | None:
    """小数收益 → 百分数，保留 digits 位。"""
    return None if x is None else round(x * 100, digits)


def pct_rank(values: list[float | None], higher_better: bool = True, na: float = 50.0) -> list[float]:
    """分位排名，0–100，并列取平均名次（与 pandas rank(pct=True) 一致）。"""
    valid = sorted(((v if higher_better else -v), i) for i, v in enumerate(values)
                   if v is not None and math.isfinite(v))
    out = [float(na)] * len(values)
    n = len(valid)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and valid[j + 1][0] == valid[i][0]:
            j += 1
        rank = ((i + j) / 2 + 1) / n * 100
        for k in range(i, j + 1):
            out[valid[k][1]] = rank
        i = j + 1
    return out


def quantile(sorted_values: list[float], q: float) -> float:
    n = len(sorted_values)
    return sorted_values[min(n - 1, max(0, int(q * n)))]


def tradable(row: dict) -> bool:
    """不碰的股票：ST、退市整理、上市不足一周的新股、3 元以下的低价股。"""
    name = row.get("name") or ""
    return not ST_RE.search(name) and not NEW_RE.match(name) and (row.get("price") or 0) >= 3


def limit_pct(code: str, market: str) -> float:
    """涨跌停幅度（小数）。创业板、科创板 20%，北交所 30%，其余 10%。"""
    if market == "BJ":
        return 0.30
    if code.startswith(("30", "688", "689")):
        return 0.20
    return 0.10


# 行业归到大类：同一大类只选一只。顺序有讲究——先匹配的先归类（「电网设备」归新能源而不是公用事业，
# 「航天航空」归军工而不是交通，「工程机械」归机械而不是基建）。
BUCKETS = (
    ("金融", ("银行", "证券", "券商", "保险", "多元金融", "信托", "期货")),
    ("医药", ("医药", "医疗", "生物", "中药", "制药", "疫苗")),
    ("食品饮料", ("酿酒", "白酒", "啤酒", "食品", "饮料", "乳", "调味")),
    ("大消费", ("家电", "零售", "百货", "旅游", "酒店", "餐饮", "美容", "纺织", "服装", "家居")),
    ("半导体电子", ("半导体", "电子", "元件", "芯片", "光学")),
    ("新能源", ("电池", "光伏", "风电", "储能", "能源金属", "电网", "电源设备", "电机")),
    ("通信计算机", ("通信", "计算机", "软件", "互联网", "游戏", "传媒", "文化")),
    ("资源周期", ("钢铁", "煤炭", "有色", "金属", "石油", "化工", "化学", "化纤", "塑料", "橡胶", "建材", "水泥", "玻璃")),
    ("公用事业", ("电力", "燃气", "水务", "环保", "公用")),
    ("军工", ("航天", "军工", "船舶", "国防")),
    ("交通运输", ("航运", "港口", "航空", "机场", "铁路", "公路", "物流")),
    ("汽车", ("汽车", "零部件")),
    ("机械设备", ("机械", "设备", "仪器", "仪表")),
    ("地产基建", ("房地产", "建筑", "装修", "工程")),
    ("农业", ("农牧", "饲料", "养殖", "种植", "渔业", "农业")),
)
FINANCIAL_WORDS = ("银行", "证券", "券商", "保险", "多元金融", "信托")


def guess_industry(name: str) -> str:
    """取不到行业时，从名字猜最常见的几类：银行、券商、保险的名字几乎都带这几个字。"""
    for word, industry in (("银行", "银行"), ("证券", "证券"), ("保险", "保险"), ("人寿", "保险")):
        if word in (name or ""):
            return industry
    return ""


def bucket_of(industry: str, name: str = "") -> str:
    industry = industry or guess_industry(name)
    for bucket, words in BUCKETS:
        if any(w in industry for w in words):
            return bucket
    return industry


def is_financial(industry: str, name: str = "") -> bool:
    text = industry or guess_industry(name)
    return any(w in text for w in FINANCIAL_WORDS)


def diversify(cands: list[dict], n: int, per_bucket: int = 2) -> list[dict]:
    """按顺序取前 n 只，同一大类（金融、医药、新能源……）最多 per_bucket 只。
    凑不满 n 只就少选几只，不为了凑数让一个行业占满名单。认不出大类的不受限制。"""
    picked, seen = [], {}
    for c in cands:
        bucket = c.get("bucket") or bucket_of(c.get("industry") or "", c.get("name") or "")
        if bucket and seen.get(bucket, 0) >= per_bucket:
            continue
        picked.append(c)
        if bucket:
            seen[bucket] = seen.get(bucket, 0) + 1
        if len(picked) == n:
            break
    return picked
