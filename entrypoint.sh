#!/bin/sh
set -e
DATABASE_URL="${DATABASE_ADMIN_URL:-$DATABASE_URL}" flask --app wsgi db upgrade
exec gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 1 --timeout 120
