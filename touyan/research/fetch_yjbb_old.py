"""研究用：2003–2014 年各期业绩报表（带公告日），存 fin/yjbb_*.json。"""
import json, os, time, httpx
HERE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
client = httpx.Client(timeout=30, headers={"User-Agent": UA, "Referer": "https://data.eastmoney.com/"})
cols = "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_MARKET,SECURITY_TYPE,REPORTDATE,NOTICE_DATE,UPDATE_DATE,BASIC_EPS,DEDUCT_BASIC_EPS,TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,WEIGHTAVG_ROE,YSTZ,SJLTZ,BPS,MGJYXJJE,XSMLL,YSHZ,SJLHZ,ASSIGNDSCRPT,ZXGXL,PUBLISHNAME"
def dc(filt):
    out, page = [], 1
    while True:
        params = {"sortColumns": "SECURITY_CODE", "sortTypes": "1", "pageSize": 500, "pageNumber": page, "reportName": "RPT_LICO_FN_CPD", "columns": cols, "filter": filt}
        for attempt in range(5):
            try:
                j = client.get("https://datacenter.eastmoney.com/api/data/v1/get", params=params).json(); break
            except Exception as exc:
                err = exc; time.sleep(2 * (attempt + 1))
        else:
            raise RuntimeError(str(err))
        res = j.get("result")
        if not res or not res.get("data"):
            break
        out += res["data"]
        if page >= (res.get("pages") or 1):
            break
        page += 1; time.sleep(0.3)
    return out
for y in range(2003, 2015):
    for md in ("03-31", "06-30", "09-30", "12-31"):
        p = f"{y}-{md}"
        path = os.path.join(HERE, "fin", f"yjbb_{p}.json")
        if os.path.exists(path):
            continue
        t0 = time.time()
        rows = dc(f"(REPORTDATE='{p}')(SECURITY_TYPE_CODE in (\"058001001\"))")
        json.dump(rows, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(p, len(rows), f"{time.time() - t0:.0f}s", flush=True)
