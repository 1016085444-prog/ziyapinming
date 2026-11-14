"""研究用：候选线索（都只用到 t 日收盘为止的数据）。"""
from lab import *
import numpy as np

UMV1000 = eligible & (rk_mv <= 1000)
UMV800 = eligible & (rk_mv <= 800)
UMV500 = eligible & (rk_mv <= 500)
UMV1500 = eligible & (rk_mv <= 1500)

with np.errstate(invalid="ignore", divide="ignore"):
    LIN = np.log(C / O)            # 日内（对数）
    LON = np.log(O / PC)           # 隔夜（对数）
    AMP = H / L - 1                # 振幅
    CLV = np.where(H > L, (C - L) / (H - L), 0.5)
    USH = (H - np.maximum(O, C)) / PC      # 上影线
    LSH = (np.minimum(O, C) - L) / PC      # 下影线
    LOGMV = np.log(FMV)

_cache = {}


def F(name):
    if name in _cache:
        return _cache[name]
    x = _make(name)
    _cache[name] = x
    return x


def _make(name):
    with np.errstate(invalid="ignore", divide="ignore"):
        if name == "r1":
            return np.where(valid, R, np.nan)
        if name.startswith("r") and name[1:].isdigit():
            return ret_k(int(name[1:]))
        if name.startswith("mom"):                  # mom120_20：跳过最近 20 天的 120 日涨幅
            k, s = name[3:].split("_")
            return ret_k(int(k), int(s))
        if name.startswith("id") and name[2:].isdigit():      # 日内累计
            return roll_sum(LIN, int(name[2:]))[0].astype(np.float32)
        if name.startswith("ov") and name[2:].isdigit():      # 隔夜累计
            return roll_sum(LON, int(name[2:]))[0].astype(np.float32)
        if name.startswith("vol"):
            return roll_std(R, int(name[3:]))
        if name.startswith("max"):
            k = int(name[3:])
            return roll_max(np.where(valid, R, np.nan), k, max(1, k // 2))
        if name.startswith("min"):
            k = int(name[3:])
            return roll_min(np.where(valid, R, np.nan), k, max(1, k // 2))
        if name.startswith("amp"):
            return roll_mean(AMP, int(name[3:]))
        if name.startswith("turn") and name[4:].isdigit():
            return roll_mean(TR, int(name[4:]))
        if name.startswith("abn"):                  # abn5_60：近 5 日换手 / 近 60 日换手
            a, b = name[3:].split("_")
            return roll_mean(TR, int(a)) / roll_mean(TR, int(b))
        if name == "size":
            return LOGMV
        if name == "amt":
            return np.log(amt60)
        if name.startswith("illiq"):
            k = int(name[5:])
            return roll_mean(np.abs(R) / (A / 1e8), k)
        if name.startswith("clv"):
            return roll_mean(np.where(valid, CLV, np.nan), int(name[3:]))
        if name.startswith("ush"):
            return roll_mean(USH, int(name[3:]))
        if name.startswith("lsh"):
            return roll_mean(LSH, int(name[3:]))
        if name.startswith("hi"):                   # 离 k 日最高价的距离
            k = int(name[2:])
            return Cf / roll_max(H, k, k // 2) - 1
        if name.startswith("lo"):
            k = int(name[2:])
            return Cf / roll_min(L, k, k // 2) - 1
        if name.startswith("skew"):
            k = int(name[4:])
            m = roll_mean(R, k)
            sd = roll_std(R, k)
            m3 = roll_mean((R - m) ** 3, k)        # 近似（用当前均值）
            return m3 / sd ** 3
        if name.startswith("upr"):                  # 上涨天数占比
            k = int(name[3:])
            s, n = roll_sum(np.where(valid, (R > 0).astype(float), np.nan), k)
            return np.where(n >= k * 0.6, s / n, np.nan).astype(np.float32)
        if name.startswith("fit"):                  # k 日对数价格对时间的拟合优度（带斜率的符号）
            k = int(name[3:])
            y = np.log(Cf.astype(np.float64))
            tt = np.arange(T, dtype=np.float64)[:, None] * np.ones((1, N))
            sy = roll_sum(y, k)[0]; syy = roll_sum(y * y, k)[0]; sxy = roll_sum(tt * y, k)[0]
            sx = roll_sum(tt, k)[0]; sxx = roll_sum(tt * tt, k)[0]
            cov = sxy - sx * sy / k; vx = sxx - sx * sx / k; vy = syy - sy * sy / k
            r2 = np.where((vx > 0) & (vy > 1e-12), cov * cov / (vx * vy), np.nan)
            return (np.sign(cov) * r2).astype(np.float32)
        if name.startswith("disc"):                 # 信息离散度：sign(涨幅)×(下跌天数占比−上涨天数占比)，越小越「温水煮青蛙」
            k = int(name[4:])
            pos = roll_sum(np.where(valid, (R > 0).astype(float), np.nan), k)[0]
            neg = roll_sum(np.where(valid, (R < 0).astype(float), np.nan), k)[0]
            return (np.sign(ret_k(k)) * (neg - pos) / k).astype(np.float32)
        if name.startswith("pvc"):                  # 量价相关：k 日收盘价与换手率的相关系数
            k = int(name[3:])
            x = Cf.astype(np.float64) / roll_mean(Cf, k).astype(np.float64)
            x = np.where(valid, x, np.nan)
            yv = np.where(valid, TR, np.nan).astype(np.float64)
            return _rcorr(x, yv, k)
        if name.startswith("pvr"):                  # 量价同向程度：k 日内（复权）收盘价与换手率的相关系数——软件里就按这个算
            k = int(name[3:])
            return _rcorr(np.where(valid, C, np.nan).astype(np.float64), np.where(valid, TR, np.nan).astype(np.float64), k)
        if name.startswith("vabn"):                 # vabn20_250：近 20 日成交股数 / 近 250 日成交股数（股数 = 成交额 / 复权价，不受解禁、送转影响）
            a, b = name[4:].split("_")
            va = np.where(valid, A / C, np.nan)
            return roll_mean(va, int(a)) / roll_mean(va, int(b), int(int(b) * 0.8))
        if name.startswith("pvv"):                  # 量价同向程度：k 日内收盘价与成交股数的相关系数
            k = int(name[3:])
            return _rcorr(np.where(valid, C, np.nan).astype(np.float64), np.where(valid, A / C, np.nan).astype(np.float64), k)
        if name.startswith("rvc"):                  # k 日涨跌幅与换手率的相关系数
            k = int(name[3:])
            return _rcorr(np.where(valid, R, np.nan).astype(np.float64), np.where(valid, TR, np.nan).astype(np.float64), k)
        if name.startswith("sharpe"):               # 涨幅 / 波动
            k = int(name[6:])
            return ret_k(k) / (roll_std(R, k) * np.sqrt(k))
        if name.startswith("dvol"):                 # 下行波动
            k = int(name[4:])
            return np.sqrt(roll_mean(np.where(valid, np.minimum(R, 0) ** 2, np.nan), k))
        if name.startswith("gapn"):                 # 近 k 日隔夜低开的平均幅度
            k = int(name[4:])
            return roll_mean(np.where(valid, OV, np.nan), k)
    raise KeyError(name)


def _rcorr(x, y, k):
    m = np.isfinite(x) & np.isfinite(y)
    x = np.where(m, x, np.nan); y = np.where(m, y, np.nan)
    sx, n = roll_sum(x, k); sy, _ = roll_sum(y, k)
    sxx, _ = roll_sum(x * x, k); syy, _ = roll_sum(y * y, k); sxy, _ = roll_sum(x * y, k)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / n; vx = sxx - sx * sx / n; vy = syy - sy * sy / n
        c = cov / np.sqrt(vx * vy)
    return np.where((n >= k * 0.6) & (vx > 0) & (vy > 0), c, np.nan).astype(np.float32)


def screen(names, hs, U, uname, nb=10):
    """打印每个线索最低组、最高组的超额和 t 值。"""
    print(f"===== 股票池：{uname}（每天分 {nb} 组；数字是相对同日池内随便买的超额%，括号里是 t 值）=====")
    print(f"{'线索':<10}" + "".join(f"| h={h-1:<3d} 最低组       最高组        " for h in hs))
    for nm in names:
        x = F(nm)
        row = f"{nm:<10}"
        for h in hs:
            out, ts = deciles(x, h, U, nm, nb=nb, quiet=True)
            row += f"| {out[0]*100:+6.2f}({ts[0]:+5.1f}) {out[-1]*100:+6.2f}({ts[-1]:+5.1f})   "
        print(row, flush=True)
