#!/usr/bin/env bash
# 阶段1 track A · FastAPI 脊椎冒烟脚本
# 起 uvicorn → curl 走通 health(免鉴权)+ 鉴权 401 + open→list→close 闭环 + 漏录防护。
# 用法:bash scripts/smoke_api.sh    (在 backend/ 下;需先 setup.sh 装好 venv + .env 有 API_TOKEN)
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BACKEND_DIR"
PY="${PY:-.venv/bin/python}"
HOST=127.0.0.1
PORT=8001
BASE="http://$HOST:$PORT/api/v1"

if [[ ! -f .env ]]; then echo "缺 .env(含 API_TOKEN);先 cp .env.example .env 并填值"; exit 1; fi
TOKEN="$(grep '^API_TOKEN=' .env | cut -d= -f2)"
if [[ "${#TOKEN}" -lt 16 ]]; then echo ".env 的 API_TOKEN 长度 < 16,拒绝起服务(fail-fast)"; exit 1; fi
AUTH=(-H "Authorization: Bearer $TOKEN")
JSON=(-H "Content-Type: application/json")

echo ">> 起 uvicorn :$PORT ..."
"$PY" -m uvicorn app.api.app:app --host "$HOST" --port "$PORT" --log-level warning >/tmp/linon_smoke.log 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  curl -s -o /dev/null -w "%{http_code}" "$BASE/health" 2>/dev/null | grep -q 200 && break
  sleep 1
done

echo "1) health(免鉴权):"; curl -s "$BASE/health"; echo
echo "2) 无 token → 401:";   curl -s -o /dev/null -w "  status=%{http_code}\n" "$BASE/positions"
echo "3) 错 token → 401:";   curl -s -o /dev/null -w "  status=%{http_code}\n" -H "Authorization: Bearer nope" "$BASE/positions"
echo "4) open:"; OPEN=$(curl -s "${AUTH[@]}" "${JSON[@]}" -d '{"code":"603986","name":"兆易创新","buy_price":100.0,"qty":200,"entry_reason":"放量突破"}' "$BASE/positions/open"); echo "  $OPEN"
PID=$(echo "$OPEN" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['position_id'])")
echo "5) list:";  curl -s "${AUTH[@]}" "$BASE/positions"; echo
echo "6) 重复 open → 409:"; curl -s -o /dev/null -w "  status=%{http_code}\n" "${AUTH[@]}" "${JSON[@]}" -d '{"code":"603986","buy_price":100.0,"qty":200,"entry_reason":"x"}' "$BASE/positions/open"
echo "7) close:"; curl -s "${AUTH[@]}" "${JSON[@]}" -d '{"sell_price":116.0}' "$BASE/positions/$PID/close"; echo
echo "8) 重复 close → 404:"; curl -s -o /dev/null -w "  status=%{http_code}\n" "${AUTH[@]}" "${JSON[@]}" -d '{"sell_price":116.0}' "$BASE/positions/$PID/close"
echo "9) device register:"; curl -s "${AUTH[@]}" "${JSON[@]}" -d '{"token":"smoke-device","platform":"ios"}' "$BASE/devices"; echo
echo "10) ack:"; curl -s "${AUTH[@]}" "${JSON[@]}" -d '{"action":"marked_close"}' "$BASE/alerts/603986/ack"; echo
echo ">> 冒烟完成。"
