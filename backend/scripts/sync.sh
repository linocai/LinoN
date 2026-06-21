#!/usr/bin/env bash
# LinoN 部署同步(plan §4 Phase 0.6,锁定约束 3:rsync over SSH,参数化 host/user/path)。
#
# 只同步 backend/(显式排除 client/ 与 data/);SSH 连接方式留占位:
#   读环境变量或 backend/.env 的 LINON_DEPLOY_HOST/USER/PATH;
#   未配置时打印指引并优雅退出(exit 0),【绝不误同步】。
#
# 用法:
#   方式一(环境变量): LINON_DEPLOY_HOST=1.2.3.4 LINON_DEPLOY_USER=root \
#                      LINON_DEPLOY_PATH=/opt/linon bash scripts/sync.sh
#   方式二(.env):     在 backend/.env 填 LINON_DEPLOY_HOST/USER/PATH 后 bash scripts/sync.sh
#   预演(不实传):     DRY_RUN=1 bash scripts/sync.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# —— 从 .env 读占位(不覆盖已设的环境变量)——
ENV_FILE="${BACKEND_DIR}/.env"
if [ -f "${ENV_FILE}" ]; then
  # 仅取 LINON_DEPLOY_* 三行,避免 source 整个 .env 引入噪声/密钥
  while IFS='=' read -r key val; do
    case "${key}" in
      LINON_DEPLOY_HOST) : "${LINON_DEPLOY_HOST:=${val}}" ;;
      LINON_DEPLOY_USER) : "${LINON_DEPLOY_USER:=${val}}" ;;
      LINON_DEPLOY_PATH) : "${LINON_DEPLOY_PATH:=${val}}" ;;
    esac
  done < <(grep -E '^LINON_DEPLOY_(HOST|USER|PATH)=' "${ENV_FILE}" || true)
fi

HOST="${LINON_DEPLOY_HOST:-}"
USER_NAME="${LINON_DEPLOY_USER:-}"
REMOTE_PATH="${LINON_DEPLOY_PATH:-}"

# —— 未配置则优雅退出,绝不误同步 ——
if [ -z "${HOST}" ] || [ -z "${USER_NAME}" ] || [ -z "${REMOTE_PATH}" ]; then
  cat <<'EOF'
[sync.sh] 部署目标未配置,已安全退出(未做任何同步)。

  请提供 ECS 连接三要素(SSH 连接方式由用户稍后给定):
    LINON_DEPLOY_HOST  例如 1.2.3.4 或 ecs.example.com
    LINON_DEPLOY_USER  例如 root
    LINON_DEPLOY_PATH  远端部署目录,例如 /opt/linon

  两种配置方式:
    1) 环境变量:
         LINON_DEPLOY_HOST=1.2.3.4 LINON_DEPLOY_USER=root \
         LINON_DEPLOY_PATH=/opt/linon bash scripts/sync.sh
    2) 写入 backend/.env(参考 .env.example 末尾的部署占位)

  仅同步 backend/(排除 client/ 与 data/)。
EOF
  exit 0
fi

# —— 选定 GNU rsync 3.x(macOS 自带 openrsync 与 --delete 不兼容,见 ~/Lino/hz_info.md)——
RSYNC_BIN="${RSYNC_BIN:-rsync}"
if ! "${RSYNC_BIN}" --version 2>/dev/null | head -1 | grep -qE 'rsync +version 3'; then
  for cand in /opt/homebrew/bin/rsync /usr/local/bin/rsync; do
    if [ -x "${cand}" ] && "${cand}" --version 2>/dev/null | head -1 | grep -qE 'rsync +version 3'; then
      RSYNC_BIN="${cand}"; break
    fi
  done
fi
if ! "${RSYNC_BIN}" --version 2>/dev/null | head -1 | grep -qE 'rsync +version 3'; then
  cat <<'EOF'
[sync.sh] 未找到 GNU rsync 3.x。macOS 自带 openrsync 与 --delete 不兼容(见 hz_info.md)。
  安装:  brew install rsync
  或指定:RSYNC_BIN=/path/to/gnu-rsync bash scripts/sync.sh
EOF
  exit 1
fi

# —— rsync:只同步 backend/,显式排除 client/(不在 backend 下,双保险)与 data/ ——
DEST="${USER_NAME}@${HOST}:${REMOTE_PATH}"
RSYNC_OPTS=(-az --delete
  --exclude '.venv/'
  --exclude '__pycache__/'
  --exclude '.pytest_cache/'
  --exclude 'data/'          # SQLite 落盘不传(远端独立库)
  --exclude '.env'           # 密钥不随同步覆盖(远端 .env 独立维护)
  --exclude 'client'         # 客户端不进后端部署
  --exclude '*.db'
  --exclude '.DS_Store'
)

if [ "${DRY_RUN:-0}" = "1" ]; then
  RSYNC_OPTS+=(--dry-run --verbose)
  echo "[sync.sh] DRY_RUN:预演,不实传"
fi

echo "[sync.sh] ${RSYNC_BIN} ${BACKEND_DIR}/  ->  ${DEST}"
"${RSYNC_BIN}" "${RSYNC_OPTS[@]}" "${BACKEND_DIR}/" "${DEST}/"
echo "[sync.sh] 完成。远端 setup:ssh ${USER_NAME}@${HOST} 'cd ${REMOTE_PATH} && bash scripts/setup.sh'"
