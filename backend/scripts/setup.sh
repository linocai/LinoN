#!/usr/bin/env bash
# LinoN 后端一键安装(plan §4 Phase 0.6,锁定约束 4:venv + requirements)。
# 幂等:建 venv、装钉死依赖、建库(调 0.4 init_db)。可重复执行不报错。
#
# 用法(在 backend/ 下或任意目录均可,脚本自定位):
#   bash scripts/setup.sh
#
# 验收:干净目录跑通建出可用 venv 与库;再跑一次不破坏现状。
set -euo pipefail

# —— 自定位到 backend/ 根 ——
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

VENV_DIR="${BACKEND_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "==> LinoN setup @ ${BACKEND_DIR}"

# 1) venv(已存在则复用,幂等)
if [ ! -d "${VENV_DIR}" ]; then
  echo "==> 建 venv: ${VENV_DIR}"
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
else
  echo "==> venv 已存在,复用"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# 2) 依赖(钉死版本;升级 pip 后装 requirements)
# pip 源:ECS 直连公网 PyPI 会超时卡死(见 ~/Lino/hz_info.md),默认走阿里云镜像;可用 PIP_INDEX_URL 覆盖。
export PIP_INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
export PIP_DEFAULT_TIMEOUT="${PIP_DEFAULT_TIMEOUT:-60}"
echo "==> pip 源: ${PIP_INDEX_URL}"
echo "==> 升级 pip"
python -m pip install --quiet --upgrade pip

echo "==> 安装钉死依赖(requirements.txt)"
python -m pip install --quiet -r "${BACKEND_DIR}/requirements.txt"

# 3) .env(缺失则从样例拷一份占位,不覆盖已有)
if [ ! -f "${BACKEND_DIR}/.env" ]; then
  echo "==> 未见 .env,从 .env.example 拷一份占位(请填 TUSHARE_TOKEN 等)"
  cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
else
  echo "==> .env 已存在,保留不动"
fi

# 4) 建库(调 0.4 init_db,幂等)
echo "==> 初始化 SQLite 四表"
python -c "from app.db import init_db; print('DB ready:', init_db())"

echo "==> setup 完成。激活:source ${VENV_DIR}/bin/activate"
echo "==> 冒烟:python scripts/smoke.py"
