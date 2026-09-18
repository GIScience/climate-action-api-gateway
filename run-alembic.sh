#!/bin/bash

set -e

alembic -c "$(alembic-config-location)" "$@"

echo "Alembic run successfully"