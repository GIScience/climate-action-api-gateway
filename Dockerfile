FROM python:3.13.5-bookworm
SHELL ["/bin/bash", "-c"]

ARG CI_JOB_TOKEN
ENV PACKAGE_NAME="api_gateway"

RUN pip install --no-cache-dir poetry==2.1.3

COPY pyproject.toml poetry.lock ./

RUN --mount=type=secret,id=CI_JOB_TOKEN,env=CI_JOB_TOKEN \
    git config --global url."https://gitlab-ci-token:${CI_JOB_TOKEN}@gitlab.heigit.org".insteadOf "ssh://git@gitlab.heigit.org:2022" && \
    poetry install --no-ansi --no-interaction --all-extras --without dev,test --no-root

# installing script seems to not work https://github.com/python-poetry/poetry/issues/10664
COPY run-alembic.sh run-alembic.sh
COPY conf conf
COPY README.md ./README.md
COPY $PACKAGE_NAME $PACKAGE_NAME

RUN poetry install --no-ansi --no-interaction --all-extras --only-root

ENTRYPOINT exec poetry run python ./${PACKAGE_NAME}/app/api.py
EXPOSE 8000
