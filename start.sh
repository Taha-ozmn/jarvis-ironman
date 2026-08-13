#!/bin/bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="${PYTHON:-/usr/local/bin/python3.11}"

if ! command -v "$PYTHON" &>/dev/null; then
  PYTHON=python3
fi

echo "⚡ JARVIS Iron Man Assistant"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━"

cd "$DIR"

if [ ! -d ".venv" ]; then
  echo "📦 Sanal ortam oluşturuluyor..."
  "$PYTHON" -m venv .venv
fi

source .venv/bin/activate
VENV_PYTHON="$DIR/.venv/bin/python3"
STAMP="$DIR/.venv/.deps_stamp"

if command -v md5 >/dev/null 2>&1; then
  REQ_HASH=$(md5 -q requirements.txt)
else
  REQ_HASH=$(shasum -a 256 requirements.txt | awk '{print $1}')
fi

if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$REQ_HASH" ]; then
  echo "📦 Bağımlılıklar yükleniyor..."
  "$VENV_PYTHON" -m pip install -q -r requirements.txt
  echo "$REQ_HASH" > "$STAMP"
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo ""
  echo "⚠️  .env dosyası oluşturuldu."
  echo "   CURSOR_API_KEY değerini düzenleyin: nano .env"
  echo ""
fi

mkdir -p workspace

echo ""
echo "🚀 JARVIS — Stark OS Browser"
echo "   Web HUD · Voice · Cursor Auto"
echo ""

exec "$VENV_PYTHON" main.py --browser "$@"
