#!/usr/bin/env bash
# SQLiteのオンラインバックアップ（運用中でも安全に取得できる）。
# crontabの例:  0 3 * * * /opt/python-bbs/deploy/scripts/backup-db.sh
set -euo pipefail

DB_PATH="${BBS_DB_PATH:-/opt/python-bbs/data/bbs.db}"
BACKUP_DIR="${BBS_BACKUP_DIR:-/opt/python-bbs/backups}"
KEEP_DAYS="${BBS_BACKUP_KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_DIR}/bbs-${STAMP}.db"

mkdir -p "${BACKUP_DIR}"

# `.backup` コマンドはSQLiteのオンラインバックアップAPIを使うため、
# アプリを止めずに一貫性のあるコピーが取れる（cpでのファイルコピーは不可。
# WALファイルが書き込み中だと壊れたコピーになり得るため）。
sqlite3 "${DB_PATH}" ".backup '${DEST}'"
gzip "${DEST}"

echo "バックアップ完了: ${DEST}.gz"

# 保持期間を超えた古いバックアップを削除
find "${BACKUP_DIR}" -name 'bbs-*.db.gz' -mtime "+${KEEP_DAYS}" -delete

echo "※オフサイト保管する場合は、ここで rclone 等を使って"
echo "  暗号化しつつ別の場所へ転送する処理を追加してください。"
