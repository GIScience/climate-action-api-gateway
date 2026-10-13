ARG BASE_IMAGE=python:3.13-slim-bookworm

# Build stage: having a build stage means temp/cache files from the build aren't persisted in the final image
FROM $BASE_IMAGE AS builder

ARG HOME=/root

# Install poetry in an isolated venv to avoid conflicts with the package venv
ARG POETRY_HOME=$HOME/poetry
ARG POETRY_VIRTUALENVS_IN_PROJECT=true
RUN --mount=type=cache,target=$HOME/.cache/pip \
    python3 -m venv $POETRY_HOME && \
    $POETRY_HOME/bin/pip install poetry==2.*
ARG PATH="$POETRY_HOME/bin:$PATH"

# Workdir in build image and deployment image must be equal for poetry generated shebangs to work
WORKDIR /home/gateway

# Install project dependencies
COPY pyproject.toml poetry.lock ./
RUN --mount=type=cache,target=$HOME/.cache/pypoetry \
    poetry install --no-ansi --no-interaction --without dev,test --no-root

# Copy the project files
ENV PACKAGE_NAME='api_gateway'
COPY $PACKAGE_NAME $PACKAGE_NAME
COPY run-alembic.sh run-alembic.sh
COPY conf conf
COPY README.md ./README.md

RUN poetry install --no-ansi --no-interaction --only-root

# Deployment stage: a smaller image with only the required files
FROM $BASE_IMAGE AS deployment

# Install system-level shared libs needed by compiled deps (e.g. rasterio -> libexpat)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends libexpat1

# Create a dedicated user to run all tasks (as non-root)
ENV USER=gateway
ARG UID=99
ARG GID=$UID
RUN addgroup gateway --gid $GID && \
    useradd -u $UID -g $GID -ms /bin/bash $USER
USER $USER

# Must be same as in builder image, see above
ENV WD=/home/gateway
WORKDIR $WD

# Copy the compiled project from the builder
COPY --from=builder --chown=$USER $WD $WD
ENV PATH="$WD/.venv/bin:$PATH"

ENTRYPOINT ["api-gateway"]
EXPOSE 8000
