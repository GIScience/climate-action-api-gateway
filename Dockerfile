FROM python:3.13-slim-bookworm AS python_base

# Install system-level shared libs needed by compiled deps (e.g. rasterio -> libexpat)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends libexpat1

# Create a dedicated user to run all tasks (as non-root)
ARG UID=99
RUN useradd -u $UID -ms /bin/bash gateway
USER gateway

ENV HOME=/home/gateway
ENV WD=$HOME/package
WORKDIR $WD

# Build stage: having a build stage means temp/cache files from the build aren't persisted in the final image
FROM python_base AS builder

ENV POETRY_HOME="~/.cache/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true
ENV PATH="$POETRY_HOME/bin:$PATH"

# Install poetry in an isolated venv to avoid conflicts with the package venv
RUN --mount=type=cache,uid=$UID,target=$HOME/.cache/pip \
    python3 -m venv $POETRY_HOME && \
    $POETRY_HOME/bin/pip install poetry==2.*

# Install project dependencies
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,uid=$UID,target=$HOME/.cache/pypoetry \
    poetry install --no-ansi --no-interaction --without dev,test --no-root

# Install the project itself
ENV PACKAGE_NAME='api_gateway'
COPY $PACKAGE_NAME $PACKAGE_NAME
# installing script seems to not work https://github.com/python-poetry/poetry/issues/10664
COPY run-alembic.sh run-alembic.sh
COPY conf conf
COPY README.md ./README.md

RUN poetry install --no-ansi --no-interaction --only-root

# Deployment stage: a smaller image with only the required files
FROM python_base AS deployment

COPY --from=builder $WD $WD

ENV PATH="$WD/.venv/bin:$PATH"

ENTRYPOINT ["api-gateway"]
EXPOSE 8000
