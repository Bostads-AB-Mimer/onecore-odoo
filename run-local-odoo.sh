#!/bin/bash

# Based on the run command for booting up Odoo in development mode:
# 
# ENV=local python3 odoo-bin 
# --addons-path="addons,/path/to/onecore-odoo" 
# -d odoo 
# --db_user=myuser 
# --db_host=localhost 
# --db_port=5432 -i base 
# -u onecore_maintenance_extension 
# -u onecore_mail_extension 
# -u onecore_ui 
# -u onecore_web_extension 
# --dev xml

# Load environment variables from .env file
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
elif [ -f $(dirname "$0")/.env ]; then
  export $(grep -v '^#' $(dirname "$0")/.env | xargs)
else
  echo "Error: .env file not found in current directory or script directory"
  exit 1
fi

# Use provided modules or default ones
if [ "$1" ]; then
    MODULES=$1
else
    MODULES=$DEFAULT_MODULES
fi

# Convert comma-separated list to space-separated for -u arguments
MODULE_ARGS=""
IFS=',' read -ra MODULE_ARRAY <<< "$MODULES"
for module in "${MODULE_ARRAY[@]}"; do
    MODULE_ARGS="$MODULE_ARGS -u $module"
done


# Run Odoo with the specified parameters
ENV=$ENV python3 "$ODOO_PATH/odoo-bin" \
  --addons-path="$ODOO_PATH/addons,$ODOO_ONECORE_PATH" \
  -d "$DB_NAME" \
  --db_user="$DB_USER" \
  --db_host="$DB_HOST" \
  --db_port="$DB_PORT" \
  -i base \
  $MODULE_ARGS \
  --dev "$DEV_MODE"

exit 0