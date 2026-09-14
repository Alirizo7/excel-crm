#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ -f .env ]; then
    set -a
    . ./.env
    set +a
fi
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
fi
if [ -z "${WORKBOOK_NODE:-}" ] && ! command -v node >/dev/null 2>&1; then
    echo 'Для формул Excel установите Node.js 22+ или задайте WORKBOOK_NODE.' >&2
    exit 1
fi
if [ ! -f scripts/calculate-workbook.bundle.mjs ]; then
    echo 'В проекте отсутствует готовый движок Excel. Выполните: pnpm install --frozen-lockfile && pnpm build' >&2
    exit 1
fi
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py bootstrap_workspace
exec .venv/bin/python manage.py runserver "127.0.0.1:${PORT:-8765}"
