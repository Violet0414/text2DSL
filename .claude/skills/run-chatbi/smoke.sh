#!/usr/bin/env bash
# ChatBI 服务冒烟驱动:启动 uvicorn → 健康探活 → 驱动 6 个 PRD 场景 → 摘要输出。
# 用法: bash .claude/skills/run-chatbi/smoke.sh   (PORT 可覆盖,默认 8301)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
PORT="${PORT:-8301}"
PY="$ROOT/poc/.venv/bin/python"
export CHATBI_WREN_BIN="${CHATBI_WREN_BIN:-$ROOT/poc/.venv/bin/wren}"
BASE="http://127.0.0.1:$PORT"

"$PY" -m uvicorn chatbi.api:app --host 127.0.0.1 --port "$PORT" >"/tmp/chatbi_smoke_$PORT.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT

ready=0
for _ in $(seq 1 30); do
  if curl -sf -m 2 "$BASE/healthz" >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != 1 ]; then
  echo "FATAL: 服务 30s 内未就绪,日志:" >&2; tail -20 "/tmp/chatbi_smoke_$PORT.log" >&2; exit 1
fi
echo "server ready: $BASE"

ask() {
  curl -s -m 90 -X POST "$BASE/api/ask" \
    -H 'Content-Type: application/json' \
    -d "{\"sessionId\": \"$1\", \"question\": \"$2\"}" \
  | "$PY" -c '
import sys, json
b = json.load(sys.stdin)
d = b["data"] or {}
t = d.get("type")
if t == "answer":
    rows = [(list(r.values())[1], round(list(r.values())[-1], 1)) for r in d["rows"][:4]]
    print("answer:", rows, "| metric:", d["metric"]["name"], "| cols:", d["columns"])
elif t == "clarification":
    print("clarify:", d["clarify_step"], d["template_id"], "| 选项:", list(d["options"]))
elif t == "miss":
    print("miss:", d["message"][:60], "| candidateId:", bool(d["candidate_id"]))
elif t == "reply":
    print("reply:", d["text"][:60], "...")
else:
    print(t, ":", d)
'
}

echo "--- S1 单指标直查 ---";      ask smoke-s1 "上个月各渠道营收"
echo "--- S2 口径歧义澄清 ---";    ask smoke-s2 "本月销售额"
echo "--- S4 未命中红线 ---";      ask smoke-s4 "库存周转率是多少"
echo "--- S5 非问数旁路 ---";      ask smoke-s5 "帮我写个周报"
echo "--- S3 多轮:第1轮 ---";      ask smoke-s3 "上个月各渠道营收"
echo "--- S3 多轮:第2轮(华南区呢) ---"; ask smoke-s3 "华南区呢"
