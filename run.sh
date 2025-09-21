#!/usr/bin/env bash
set -euo pipefail

# === 可調整參數 ===
BASE_URL="${BASE_URL:-http://localhost:8000}"   # FastAPI 服務位址
CASE_NAME="${CASE_NAME:-Demo Case}"             # 案件名稱
CASE_NOTE="${CASE_NOTE:-PPT/PDF convert test}"  # 案件備註
OUT_DIR="${OUT_DIR:-./downloads}"               # 下載結果存放目錄

# 轉檔選項
DPI="${DPI:-220}"
MAX_SIDE="${MAX_SIDE:-}"            # 留空代表不限制
IMAGE_FORMAT="${IMAGE_FORMAT:-PNG}" # PNG / JPEG / WEBP / TIFF
PACK_ZIP="${PACK_ZIP:-true}"
FILENAME_PREFIX="${FILENAME_PREFIX:-page}"

# 輪詢間隔與逾時
POLL_INTERVAL="${POLL_INTERVAL:-2}"    # 秒
POLL_TIMEOUT="${POLL_TIMEOUT:-300}"    # 最多等 300 秒

usage() {
  cat <<EOF
用法：
  $(basename "$0") <file1> [file2 ...]
環境變數：
  BASE_URL         預設 $BASE_URL
  CASE_NAME        預設 "$CASE_NAME"
  CASE_NOTE        預設 "$CASE_NOTE"
  OUT_DIR          預設 $OUT_DIR
  DPI              預設 $DPI
  MAX_SIDE         預設 "$MAX_SIDE" (空=不限制)
  IMAGE_FORMAT     預設 $IMAGE_FORMAT
  PACK_ZIP         預設 $PACK_ZIP
  FILENAME_PREFIX  預設 $FILENAME_PREFIX
  POLL_INTERVAL    預設 $POLL_INTERVAL
  POLL_TIMEOUT     預設 $POLL_TIMEOUT
EOF
  exit 1
}

[[ $# -ge 1 ]] || usage

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "❌ 缺少指令：$1"; exit 1; }
}
need curl
need jq

mkdir -p "$OUT_DIR"

# 1) 建立案件
echo "➡️  建立案件：$CASE_NAME"
CASE_JSON="$(curl -sS -X POST "$BASE_URL/cases" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$CASE_NAME\",\"note\":\"$CASE_NOTE\"}")"

CASE_ID="$(echo "$CASE_JSON" | jq -r '.case_id')"
[[ "$CASE_ID" != "null" && -n "$CASE_ID" ]] || { echo "❌ 建立案件失敗：$CASE_JSON"; exit 1; }
echo "✅  案件建立成功：$CASE_ID"

# 2) 上傳檔案
declare -a FILENAMES=()
for f in "$@"; do
  [[ -f "$f" ]] || { echo "❌ 找不到檔案：$f"; exit 1; }
  bn="$(basename "$f")"
  echo "⬆️  上傳檔案：$bn"
  curl -sS -X POST "$BASE_URL/cases/$CASE_ID/files" \
    -F "file=@$f" >/dev/null
  FILENAMES+=("$bn")
done

# 3) 觸發轉檔
echo "🚀  觸發轉檔：${FILENAMES[*]}"
FORM_ARGS=()
for fn in "${FILENAMES[@]}"; do
  FORM_ARGS+=(-F "filenames=$fn")
done

[[ -n "$MAX_SIDE" ]] && FORM_ARGS+=(-F "max_side=$MAX_SIDE")

TRIGGER_JSON="$(curl -sS -X POST "$BASE_URL/cases/$CASE_ID/convert" \
  -F "dpi=$DPI" \
  -F "image_format=$IMAGE_FORMAT" \
  -F "pack_zip=$PACK_ZIP" \
  -F "filename_prefix=$FILENAME_PREFIX" \
  "${FORM_ARGS[@]}")"

QUEUED="$(echo "$TRIGGER_JSON" | jq -r '.queued')"
[[ "$QUEUED" == "true" ]] || { echo "❌ 觸發轉檔失敗：$TRIGGER_JSON"; exit 1; }
echo "⏱️  已排程轉檔，開始輪詢結果…"

# 4) 輪詢結果是否產生 ZIP（或至少頁圖）
deadline=$(( $(date +%s) + POLL_TIMEOUT ))
RESULTS_BEFORE="$(curl -sS "$BASE_URL/cases/$CASE_ID/results" | jq -r '.results[]?')"

has_new_results() {
  local current; current="$(curl -sS "$BASE_URL/cases/$CASE_ID/results" | jq -r '.results[]?')"
  # 檢查是否出現新的 zip 或新檔案
  diff <(echo "$RESULTS_BEFORE") <(echo "$current") >/dev/null 2>&1 || return 0
  return 1
}

until has_new_results; do
  now=$(date +%s)
  if (( now > deadline )); then
    echo "⚠️  等待逾時（${POLL_TIMEOUT}s）。你可稍後手動下載：$BASE_URL/cases/$CASE_ID/results"
    break
  fi
  sleep "$POLL_INTERVAL"
done

# 5) 下載整包 ZIP（若存在）
ZIP_URL="$BASE_URL/cases/$CASE_ID/results.zip"
ZIP_PATH="$OUT_DIR/${CASE_ID}_results.zip"

echo "⬇️  嘗試下載整包結果：$ZIP_URL"
if curl -fsS -o "$ZIP_PATH" "$ZIP_URL"; then
  echo "✅  已下載：$ZIP_PATH"
else
  echo "⚠️  下載整包 ZIP 失敗，改列出結果清單："
  curl -sS "$BASE_URL/cases/$CASE_ID/results" | jq .
  echo "可逐檔下載：$BASE_URL/cases/$CASE_ID/results/<filename>"
fi

echo "🎉 完成"
