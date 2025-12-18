#!/bin/bash

set -e

poetry run alembic -c "$(poetry run alembic-config-location)" "$@"

echo "Alembic run successfully"