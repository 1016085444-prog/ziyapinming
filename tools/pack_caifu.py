"""把财富站打成一个可直接上传到 CloudBase 云托管的 zip。

    .venv/bin/python tools/pack_caifu.py

产物 dist/caifu-deploy.zip，根目录就是一个完整的构建上下文：Dockerfile 已经
放在根上、名字就叫 Dockerfile，云托管「本地代码上传」时什么都不用改。
只打财富站需要的文件，主站的页面、二维码、AI 与支付模块都不进包。
"""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "caifu-deploy.zip"

DIRS = ("bazi", "ziwei", "caifu")
FILES = {
    "Dockerfile.caifu": "Dockerfile",
    "requirements.txt": "requirements.txt",
    ".dockerignore": ".dockerignore",
    "static/common.js": "static/common.js",
    "static/places.js": "static/places.js",
}


def main():
    OUT.parent.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for src, dst in FILES.items():
            z.write(ROOT / src, dst)
            n += 1
        for d in DIRS:
            for f in sorted((ROOT / d).rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                    z.write(f, f.relative_to(ROOT).as_posix())
                    n += 1
    print("{} 个文件 → {}（{:.0f} KB）".format(n, OUT.relative_to(ROOT), OUT.stat().st_size / 1024))


if __name__ == "__main__":
    main()
