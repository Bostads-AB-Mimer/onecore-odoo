#!/bin/bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source "$SCRIPT_DIR/.env"

TEST_DB_NAME="test_onecore_$(date +%s)"

echo "Running tests with database: $TEST_DB_NAME"

ONECORE_MODULES="onecore_maintenance_extension,onecore_mail_extension,onecore_base_extension,onecore_web_extension,onecore_api,onecore_ui"

ENV=local python3 "$ODOO_PATH/odoo-bin" \
  --addons-path="$ODOO_PATH/addons,$ODOO_ONECORE_PATH" \
  -d "$TEST_DB_NAME" \
  --db_user="$DB_USER" \
  --db_host="$DB_HOST" \
  --db_port="$DB_PORT" \
  -i $ONECORE_MODULES \
  --test-enable \
  --stop-after-init \
  --test-tags=onecore \
  --log-level=test
