#!/usr/bin/env bash
# オリジンサーバーのファイアウォール設定。
#
# 方針: 公開インターネットからの着信は一切受け付けない。
#   - アプリ(gunicorn)は 127.0.0.1 だけで待ち受けるため、そもそも外部到達不能。
#   - Cloudflare Tunnel (cloudflared) はアプリへ"発信"接続するだけなので、
#     80/443番ポートを開ける必要が無い（ポートフォワード自体が不要）。
#   - 管理アクセス（SSH）は Tailscale のインターフェース経由でのみ許可する。
#
# 使い方: sudo bash deploy/scripts/firewall-ufw.sh <tailscaleのインターフェース名>
#         （通常は tailscale0。`tailscale status` や `ip a` で確認）
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "root権限で実行してください（sudo bash $0 ...）" >&2
    exit 1
fi

TS_IFACE="${1:-tailscale0}"

echo "== 既定ポリシー: すべて拒否 =="
ufw --force reset
ufw default deny incoming
ufw default allow outgoing

echo "== Tailscaleインターフェース(${TS_IFACE})からのSSHのみ許可 =="
ufw allow in on "${TS_IFACE}" to any port 22 proto tcp

echo "== Tailscale自身のUDPポート(NAT越え用)は全インターフェースで許可 =="
ufw allow 41641/udp

# 80/443はここでは一切開けない。cloudflaredはアウトバウンド接続のみを使う。
# 直接ポート開放する構成（従来型リバースプロキシ）に切り替える場合だけ、
# 該当ポートの許可ルールを別途追加すること。

ufw --force enable
ufw status verbose
