# 投研智能体 —— 容器部署（腾讯云 CloudBase 云托管、阿里云、Render、自建服务器……）
#
# 构建目录（上下文）选 touyan/：
#     docker build -t touyan ./touyan
#     docker run -d -p 8600:8600 -e APP_PASSWORD=你的密码 -e DEEPSEEK_API_KEY=sk-xxx -v touyan-data:/data touyan
#
# 部署到公网务必设置 APP_PASSWORD，否则深度分析和设置只对本机开放（容器外访问都算远程）。
# CloudBase 云托管默认监听 80 端口：在服务设置里加环境变量 PORT=80 即可。

FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TOUYAN_DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8600

# 先装依赖再拷代码：依赖没变时这一层命中缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 设置、历史记录、缓存都在 /data，挂卷后重建容器不丢
VOLUME ["/data"]
EXPOSE 8600

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
