"""实验 3：几十种线索的大筛查。看每种线索最低/最高的十分之一，之后相对「同日随便买」多赚还是少赚。"""
import sys
from feat import *
names = ["r1", "r3", "r5", "r10", "r20", "r60", "r120", "r250", "mom120_20", "mom250_20",
         "id5", "id20", "id60", "ov5", "ov20", "ov60",
         "vol20", "vol60", "max20", "min20", "amp20", "skew20", "dvol60",
         "turn5", "turn20", "turn60", "abn5_60", "abn20_250", "size", "amt", "illiq20",
         "clv5", "clv20", "ush20", "lsh20", "hi250", "hi60", "lo60",
         "upr60", "fit60", "disc60", "disc120", "pvc20", "rvc20", "sharpe60", "sharpe120"]
which = sys.argv[1] if len(sys.argv) > 1 else "all"
pools = {"all": (UALL, "全市场(日均成交>3000万)"), "mv1000": (UMV1000, "流通市值前1000"), "mv300": (U300, "流通市值前300"), "amt1000": (U1000, "成交额前1000")}
U, uname = pools[which]
screen(names, (3, 6, 11, 21, 61), U, uname)
