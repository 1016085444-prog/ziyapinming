"""重新测定财富指数的校准常量，写回 caifu/calibration.py。

为什么需要：五力各自的规则条数与权重不同，原始分散布相差很大；不归一的话，
「守财 78」和「偏财 78」代表的稀有程度不一样。「胜过 X% 的命盘」也必须来自
实测分布，而不是拍脑袋——这是页面上最显眼的一个数字，必须经得起复算。

改动 caifu/report.py 里任何规则权重后都要重跑：

    .venv/bin/python tools/calibrate_caifu.py

样本：1950–2010 年间均匀随机的出生时刻，男女各半，经度取北京。
固定随机种子，重跑结果可复现。
"""

import importlib
import random
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bazi.chart import build_chart as bazi_chart      # noqa: E402
from ziwei.chart import build_chart as ziwei_chart    # noqa: E402

N = 4000
OUT = ROOT / "caifu" / "calibration.py"
PLACEHOLDER = [50] * 59


def samples():
    rnd = random.Random(20261125)
    for _ in range(N):
        y = rnd.randint(1950, 2010)
        m = rnd.randint(1, 12)
        d = rnd.randint(1, 28)
        h, mi = rnd.randint(0, 23), rnd.randint(0, 59)
        g = rnd.choice(("male", "female"))
        yield (bazi_chart(y, m, d, h, mi, gender=g),
               ziwei_chart(y, m, d, h, mi, gender=g))


def write(forces, composite, pcts):
    body = ['"""财富指数的校准常量 —— 由 tools/calibrate_caifu.py 生成，请勿手改。',
            '',
            '样本 {} 张随机命盘。FORCES / COMPOSITE 为 (均值, 标准差)，'.format(N),
            'CDF[i] 为财富指数 = 38+i 时「胜过」的命盘百分比（同分者算一半）。"""',
            '',
            'FORCES = {']
    for k, (m, s) in forces.items():
        body.append('    "{}": ({:.2f}, {:.2f}),'.format(k, m, s))
    body.append('}')
    body.append('COMPOSITE = ({:.2f}, {:.2f})'.format(*composite))
    body.append('CDF = [')
    for i in range(0, len(pcts), 10):
        body.append('    ' + ', '.join(str(p) for p in pcts[i:i + 10]) + ',')
    body.append(']')
    OUT.write_text("\n".join(body) + "\n", encoding="utf-8")


def main():
    charts = list(samples())
    # 先写一份占位常量：第一轮只用原始分，与旧常量无关；这样即便旧文件
    # 缺字段（例如表结构改过），也不会卡在 import 上。
    names = ("正财力", "偏财力", "守财力", "创富力", "贵人财")
    write({k: (0.0, 1.0) for k in names}, (68.0, 12.0), PLACEHOLDER)
    import caifu.report as rep

    # 第一轮：五力原始分 → 均值与标准差
    raws = {k: [] for k in rep.FORCE_NAMES}
    for bz, zw in charts:
        f, _ = rep.raw_scores(bz, zw)
        for k in raws:
            raws[k].append(f[k])
    forces = {k: (st.mean(v), st.pstdev(v)) for k, v in raws.items()}
    write(forces, (68.0, 12.0), PLACEHOLDER)

    # 第二轮：用新的五力常量算合成分 → 均值与标准差
    importlib.reload(sys.modules["caifu.calibration"])
    rep = importlib.reload(rep)
    comps = [rep.raw_scores(bz, zw)[1] for bz, zw in charts]
    composite = (st.mean(comps), st.pstdev(comps))
    write(forces, composite, PLACEHOLDER)

    # 第三轮：归一后的财富指数 → 每个整数分的「胜过」百分比
    importlib.reload(sys.modules["caifu.calibration"])
    rep = importlib.reload(rep)
    idx = [rep._clamp(rep._normalize(c, composite)) for c in comps]
    pcts = []
    for score in range(rep.FLOOR, rep.CEIL + 1):
        below = sum(1 for x in idx if x < score)
        same = sum(1 for x in idx if x == score)
        pcts.append(max(1, min(99, round(100 * (below + same / 2) / N))))
    write(forces, composite, pcts)

    print("五力：")
    for k, (m, s) in forces.items():
        print("  {} 均值 {:.2f} 标准差 {:.2f}".format(k, m, s))
    print("合成：均值 {:.2f} 标准差 {:.2f}".format(*composite))
    print("CDF：", pcts)


if __name__ == "__main__":
    main()
