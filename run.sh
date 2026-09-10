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
if [ ! -d node_modules/@univerjs/preset-sheets-node-core ]; then
    echo 'Для редактора Excel выполните: pnpm install --frozen-lockfile && pnpm build' >&2
    exit 1
fi
.venv/bin/python manage.py migrate --noinput
exec .venv/bin/python manage.py runserver "127.0.0.1:${PORT:-8765}"
