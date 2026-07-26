# 腾讯云 CloudBase「云托管」/ 任何支持 Dockerfile 的平台都用这个。
#
# 注意：本项目跑不了「静态网站托管」——那类产品只分发死文件，不会执行
# app.py，排盘接口 /api/chart 和微信配置 /api/config 都会 404。

FROM python:3.12-slim

WORKDIR /app

# 先装依赖再拷代码：依赖没变时这一层命中缓存，后续重建快很多
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# CloudBase 云托管默认监听 80；平台若注入 PORT 则以平台为准
ENV PORT=80
EXPOSE 80

# 用 sh -c 是为了让 ${PORT} 在运行时展开；exec 形式拿不到环境变量
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
