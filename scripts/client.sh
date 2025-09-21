#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
DPI="${DPI:-220}"
IMAGE_FORMAT="${IMAGE_FORMAT:-PNG}"
MAX_SIDE="${MAX_SIDE:-}"         # 例如 2000；空=不限制
POLL_INTERVAL="${POLL_INTERVAL:-2}"
POLL_TIMEOUT="${POLL_TIMEOUT:-600}"

usage(){ echo "用法: $(basename "$0") <file1> [file2 ...]"; exit 1; }
[[ $# -ge 1 ]] || usage

need(){ command -v "$1" >/dev/null 2>&1 || { echo "❌ 缺少指令：$1"; exit 1; }; }
need curl
need jq

# 1) 多檔上傳
echo "⬆️  上傳檔案..."
form=()
for f in "$@"; do
  [[ -f "$f" ]] || { echo "❌ 找不到檔案：$f"; exit 1; }
  form+=(-F "files=@${f}")
done
UPLOAD_JSON="$(curl -sS -X POST "$BASE_URL/files" "${form[@]}")"
echo "↩️  $UPLOAD_JSON"
file_ids=($(echo "$UPLOAD_JSON" | jq -r '.file_ids[]'))

# 2) 觸發任務（doc_convert）
echo "🚀  觸發任務 doc_convert ..."
body=$(jq -nc --argjson ids "$(printf '%s\n' "${file_ids[@]}" | jq -R . | jq -s .)" \
               --arg name "doc_convert" \
               --arg fmt "$IMAGE_FORMAT" \
               --argjson dpi "$DPI" \
               --argjson max "${MAX_SIDE:-null}" \
               '{file_ids:$ids,name:$name,params:{image_format:$fmt,dpi:$dpi, max_side:$max}}')
RUN_JSON="$(curl -sS -X POST "$BASE_URL/files:run" -H "Content-Type: application/json" -d "$body")"
echo "↩️  $RUN_JSON"
run_ids=($(echo "$RUN_JSON" | jq -r '.runs[].task_run_id'))

# 3) 輪詢每個任務
deadline=$(( $(date +%s) + POLL_TIMEOUT ))
declare -A done
echo "⏱️  輪詢任務狀態..."
while :; do
  all_done=true
  for rid in "${run_ids[@]}"; do
    [[ "${done[$rid]:-}" == "1" ]] && continue
    st_json="$(curl -sS "$BASE_URL/runs/$rid")" || st_json='{}'
    status="$(echo "$st_json" | jq -r '.status // "UNKNOWN"')"
    echo " - $rid → $status"
    case "$status" in
      SUCCEEDED|FAILED) done[$rid]=1 ;;
      *) all_done=false ;;
    esac
  done
  $all_done && break
  now=$(date +%s); (( now > deadline )) && { echo "⚠️ 等待逾時"; break; }
  sleep "$POLL_INTERVAL"
done

echo "🎉 完成（如需下載產物，請到 MinIO console 或之後加下載端點）"
