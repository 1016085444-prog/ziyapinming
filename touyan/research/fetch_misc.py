"""研究用：指数基准、ETF 日线；业绩报表、业绩预告（带公告日）。"""
import json, os, sys, time
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["TOUYAN_DATA_DIR"] = os.path.join(HERE, "appdata")
sys.path.insert(0, ROOT)
from market import tencent  # noqa: E402
import httpx

what = sys.argv[1]
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

def save(path, bars):
    np.savez_compressed(path,
        d=np.array([int(b.date.replace("-", "")) for b in bars], dtype=np.int32),
        o=np.array([b.open for b in bars], dtype=np.float32), h=np.array([b.high for b in bars], dtype=np.float32),
        l=np.array([b.low for b in bars], dtype=np.float32), c=np.array([b.close for b in bars], dtype=np.float32),
        v=np.array([b.volume or 0 for b in bars], dtype=np.float32),
        a=np.array([b.amount if b.amount is not None else np.nan for b in bars], dtype=np.float64),
        t=np.array([b.turnover if b.turnover is not None else np.nan for b in bars], dtype=np.float32))

if what == "index":
    os.makedirs(os.path.join(HERE, "index"), exist_ok=True)
    idx = {"sh000001": "上证指数", "sh000300": "沪深300", "sh000905": "中证500", "sh000852": "中证1000", "sz399006": "创业板指",
           "sh000016": "上证50", "sh000688": "科创50", "sz399303": "国证2000", "sh000922": "中证红利", "sz399001": "深证成指",
           "sh000985": "中证全指", "sh000906": "中证800", "sz399005": "中小100", "sh000015": "红利指数", "sz399324": "深证红利"}
    for sym, name in idx.items():
        try:
            bars = tencent.kline(sym, 2600)
            save(os.path.join(HERE, "index", sym + ".npz"), bars)
            print(sym, name, len(bars), bars[0].date, bars[-1].date, bars[-1].close, flush=True)
        except Exception as exc:
            print(sym, name, "ERR", type(exc).__name__, exc, flush=True)

if what == "etf":
    os.makedirs(os.path.join(HERE, "etf"), exist_ok=True)
    sys.path.insert(0, ROOT)
    from daily import mid
    pool = list(mid.ETF_POOL) if hasattr(mid, "ETF_POOL") else []
    print("pool sample", pool[:3], flush=True)
    for item in pool:
        code = item[0] if isinstance(item, (tuple, list)) else item.get("code")
        sym = ("sh" if code.startswith(("5", "6")) else "sz") + code
        try:
            bars = tencent.kline(sym, 2600)
            save(os.path.join(HERE, "etf", code + ".npz"), bars)
            print(sym, len(bars), bars[0].date, bars[-1].date, flush=True)
        except Exception as exc:
            print(sym, "ERR", type(exc).__name__, exc, flush=True)

def dc(report, filt, sort="NOTICE_DATE", cols="ALL", page_size=500, max_pages=10000, st="-1"):
    client = httpx.Client(timeout=30, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
    out, page, pages = [], 1, None
    while True:
        params = {"sortColumns": sort, "sortTypes": st, "pageSize": page_size, "pageNumber": page,
                  "reportName": report, "columns": cols, "filter": filt}
        for attempt in range(5):
            try:
                r = client.get("https://datacenter.eastmoney.com/api/data/v1/get", params=params)
                j = r.json()
                break
            except Exception as exc:
                err = exc
                time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(f"{report} page {page}: {err}")
        res = j.get("result")
        if not res or not res.get("data"):
            if page == 1:
                print("no data", str(j)[:200], flush=True)
            break
        out += res["data"]
        pages = res.get("pages") or 1
        if page >= pages or page >= max_pages:
            break
        page += 1
        time.sleep(0.35)
    return out

if what == "yjbb":
    # 业绩报表：每个报告期一份；只留沪深 A 股
    os.makedirs(os.path.join(HERE, "fin"), exist_ok=True)
    cols = "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_MARKET,SECURITY_TYPE,REPORTDATE,NOTICE_DATE,UPDATE_DATE,BASIC_EPS,DEDUCT_BASIC_EPS,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,WEIGHTAVG_ROE,YSTZ,SJLTZ,BPS,MGJYXJJE,XSMLL,YSHZ,SJLHZ,ASSIGNDSCRPT,ZXGXL,PUBLISHNAME"
    periods = []
    for y in range(2015, 2027):
        for md in ("03-31", "06-30", "09-30", "12-31"):
            p = f"{y}-{md}"
            if p <= "2026-09-30":
                periods.append(p)
    for p in periods:
        path = os.path.join(HERE, "fin", f"yjbb_{p}.json")
        if os.path.exists(path):
            continue
        t0 = time.time()
        rows = dc("RPT_LICO_FN_CPD", f"(REPORTDATE='{p}')(SECURITY_TYPE_CODE in (\"058001001\"))", cols=cols, sort="SECURITY_CODE", st="1")
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(p, len(rows), f"{time.time() - t0:.0f}s", flush=True)

if what == "yjyg":
    os.makedirs(os.path.join(HERE, "fin"), exist_ok=True)
    cols = "SECURITY_CODE,SECURITY_NAME_ABBR,NOTICE_DATE,REPORT_DATE,PREDICT_FINANCE_CODE,PREDICT_FINANCE,PREDICT_AMT_LOWER,PREDICT_AMT_UPPER,ADD_AMP_LOWER,ADD_AMP_UPPER,PREDICT_TYPE,PREYEAR_SAME_PERIOD,TRADE_MARKET,SECURITY_TYPE"
    periods = []
    for y in range(2015, 2027):
        for md in ("03-31", "06-30", "09-30", "12-31"):
            p = f"{y}-{md}"
            if p <= "2026-12-31":
                periods.append(p)
    for p in periods:
        path = os.path.join(HERE, "fin", f"yjyg_{p}.json")
        if os.path.exists(path):
            continue
        t0 = time.time()
        rows = dc("RPT_PUBLIC_OP_NEWPREDICT", f"(REPORT_DATE='{p}')", cols=cols, sort="SECURITY_CODE,PREDICT_FINANCE_CODE,NOTICE_DATE", st="1,1,1")
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(p, len(rows), f"{time.time() - t0:.0f}s", flush=True)

if what == "probe":
    rows = dc("RPT_LICO_FN_CPD", "(REPORTDATE='2025-09-30')(SECURITY_TYPE_CODE in (\"058001001\"))", page_size=5, max_pages=1)
    for r in rows[:3]:
        print({k: r[k] for k in ("SECURITY_CODE", "SECURITY_NAME_ABBR", "TRADE_MARKET", "SECURITY_TYPE", "SECURITY_TYPE_CODE", "REPORTDATE", "NOTICE_DATE", "UPDATE_DATE", "SJLTZ", "YSTZ", "DEDUCT_BASIC_EPS")})
    rows = dc("RPT_LICO_FN_CPD", "(REPORTDATE='2019-12-31')(SECURITY_CODE=\"600519\")", page_size=5, max_pages=1)
    for r in rows[:3]:
        print({k: r[k] for k in ("SECURITY_CODE", "SECURITY_NAME_ABBR", "TRADE_MARKET", "SECURITY_TYPE", "SECURITY_TYPE_CODE", "REPORTDATE", "NOTICE_DATE", "UPDATE_DATE", "SJLTZ", "YSTZ", "DEDUCT_BASIC_EPS")})
