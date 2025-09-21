#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
if [[ -f .env ]]; then export $(grep -v '^#' .env | xargs); fi
exec celery -A worker.cel worker --loglevel=info -Q default