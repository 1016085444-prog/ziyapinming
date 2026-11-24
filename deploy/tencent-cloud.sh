#!/usr/bin/env bash
# 子牙品命 —— 腾讯云轻量应用服务器（Ubuntu / Debian）一键部署脚本
# 用法（在腾讯云服务器 root 终端执行）：
#   ADMIN_TOKEN='你自定义的高强度后台口令' bash deploy/tencent-cloud.sh
#
# 可选环境变量：
#   DOMAIN='你的域名'           # 若已绑定域名并解析到本机，可填入自动配 Nginx
#   WECHAT_ID='ziyapinming'    # 默认 ziyapinming
#   REPO_URL='https://github.com/1016085444-prog/ziyapinming.git'

set -euo pipefail

APP_DIR="/opt/ziyapinming"
DATA_DIR="/var/lib/ziyapinming"
ENV_FILE="/etc/ziyapinming.env"
SERVICE_FILE="/etc/systemd/system/ziyapinming.service"
REPO_URL="${REPO_URL:-https://github.com/1016085444-prog/ziyapinming.git}"
WECHAT_ID="${WECHAT_ID:-ziyapinming}"
DOMAIN="${DOMAIN:-_}"

if [[ -z "${ADMIN_TOKEN:-}" ]]; then
  echo "错误：请先通过环境变量传入管理后台口令，例如："
  echo "  ADMIN_TOKEN='你的强密码' bash deploy/tencent-cloud.sh"
  exit 1
fi

echo "==> [1/6] 安装基础运行环境（Python3 / venv / Git / Nginx）"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git nginx

echo "==> [2/6] 拉取或更新 GitHub 代码至 ${APP_DIR}"
if [[ -d "${APP_DIR}/.git" ]]; then
  git -C "${APP_DIR}" pull --ff-only origin main
else
  git clone "${REPO_URL}" "${APP_DIR}"
fi

echo "==> [3/6] 创建虚拟环境并安装依赖"
python3 -m venv "${APP_DIR}/.venv"
"${APP_DIR}/.venv/bin/pip" install --upgrade pip
"${APP_DIR}/.venv/bin/pip" install -r "${APP_DIR}/requirements.txt"

echo "==> [4/6] 初始化持久化卡密目录 ${DATA_DIR} 与环境变量 ${ENV_FILE}"
mkdir -p "${DATA_DIR}"
cat > "${ENV_FILE}" <<EOF
REQUIRE_CODE=1
WECHAT_ID=${WECHAT_ID}
CODES_DB_PATH=${DATA_DIR}/codes.db
ADMIN_TOKEN=${ADMIN_TOKEN}
EOF
chmod 600 "${ENV_FILE}"

echo "==> [5/6] 配置 systemd 守护服务（开机自启 + 异常自动拉起）"
cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=Ziyapinming Bazi & Ziwei Web Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now ziyapinming
systemctl restart ziyapinming

echo "==> [6/6] 配置 Nginx 反向代理（80 端口 → 127.0.0.1:8000）"
cat > /etc/nginx/sites-available/ziyapinming <<EOF
server {
    listen 80;
    server_name ${DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
ln -sf /etc/nginx/sites-available/ziyapinming /etc/nginx/sites-enabled/ziyapinming
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

echo ""
echo "============================================================"
echo "部署完成！"
echo "  排盘首页：http://<你的服务器公网IP或域名>/"
echo "  紫微页面：http://<你的服务器公网IP或域名>/ziwei"
echo "  发卡后台：http://<你的服务器公网IP或域名>/admin"
echo "  卡密库位置：${DATA_DIR}/codes.db（更新代码不会清空）"
echo "============================================================"
