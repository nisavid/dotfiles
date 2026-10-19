# Build with this skill's directory as context, never with HOME as context.
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS base

RUN apt-get update \
    && apt-get install --yes --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/trigger
COPY runtime/package.json runtime/package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund \
    && npm cache clean --force \
    && ln -s /opt/trigger/node_modules/.bin/codex /usr/local/bin/codex \
    && ln -s /opt/trigger/node_modules/.bin/acpx /usr/local/bin/acpx \
    && ln -s /opt/trigger/node_modules/.bin/codex-acp /usr/local/bin/codex-acp \
    && test "$(codex --version)" = "codex-cli 0.163.0" \
    && test "$(acpx --version)" = "0.19.6"

COPY scripts/trigger_eval_broker.py scripts/trigger_eval_worker.py ./
RUN mkdir -p /broker-socket /home/probe /work \
    && chown 1000:1000 /broker-socket /home/probe /work

ENV PATH="/opt/trigger/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    HOME="/home/probe" \
    CODEX_HOME="/home/probe/.codex" \
    NO_COLOR="1"
USER 1000:1000
WORKDIR /work
ENTRYPOINT []
CMD ["python3", "-I", "/opt/trigger/trigger_eval_worker.py", "serve"]

# This fixture is absent from the production target. It never contacts a model.
FROM base AS container-tests
COPY runtime/test-fixtures/container_fixture_broker.py /opt/trigger/container_fixture_broker.py

FROM base AS runtime
