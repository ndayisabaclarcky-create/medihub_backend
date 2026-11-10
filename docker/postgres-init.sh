#!/bin/sh
set -eu

psql --username "$POSTGRES_USER" --dbname postgres \
  --set=ON_ERROR_STOP=1 \
  --set=app_password="$DB_PASSWORD" \
  --file=/opt/medihub-db-setup.sql
