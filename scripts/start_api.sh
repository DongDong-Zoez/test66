#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ -f .env ]]; then export $(grep -v '^#' .env | xargs); fi
exec uvicorn app:app --host 0.0.0.0 --port 8000 --reload