#!/usr/bin/env bash
# 更新デプロイの最小スクリプト。Tailscale経由でSSHした後、サーバー上で実行する想定。
set -euo pipefail

APP_DIR="${BBS_APP_DIR:-/opt/python-bbs}"
SERVICE="${BBS_SERVICE_NAME:-python-bbs}"

cd "${APP_DIR}"
git pull --ff-only
"${APP_DIR}/venv/bin/pip" install -r requirements.txt
sudo systemctl restart "${SERVICE}"
sudo systemctl --no-pager --full status "${SERVICE}" | head -n 10
