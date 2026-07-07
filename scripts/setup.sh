#!/usr/bin/env bash
set -e
pip install -r requirements/dev.txt
[ -f .env ] || cp .env.example .env
echo "Done. Edit .env then: make dev"
