FROM python:3.11.5-bookworm

ENV PACKAGE_NAME='api_gateway'

RUN pip install --no-cache-dir poetry==1.7.1

COPY pyproject.toml poetry.lock ./

RUN --mount=type=secret,id=CI_JOB_TOKEN \
    export CI_JOB_TOKEN=$(cat /run/secrets/CI_JOB_TOKEN) && \
    git config --global url."https://gitlab-ci-token:${CI_JOB_TOKEN}@gitlab.gistools.geog.uni-heidelberg.de".insteadOf "ssh://git@gitlab.gistools.geog.uni-heidelberg.de:2022" && \
    poetry install --no-ansi --no-interaction --all-extras --without dev --no-root

COPY $PACKAGE_NAME $PACKAGE_NAME
COPY conf conf
COPY README.md ./README.md

RUN poetry install --no-ansi --no-interaction --all-extras --without dev

SHELL ["/bin/bash", "-c"]
ENTRYPOINT poetry run python ./${PACKAGE_NAME}/app/api.py
EXPOSE 8000
