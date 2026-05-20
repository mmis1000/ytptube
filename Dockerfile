FROM node:lts-alpine AS ui_builder

WORKDIR /app
COPY ui ./
ENV NODE_ENV=production
RUN if [ ! -f "/app/exported/index.html" ]; then \
  npm install -g bun && \
  NODE_ENV=production bun install --frozen-lockfile --production && \
  bun run generate; \
  else echo "Skipping UI build, already built."; fi

FROM node:20-bookworm AS translator_node_builder

WORKDIR /build/translator
COPY translator/package.json translator/package-lock.json ./
RUN npm ci
COPY translator/ ./
RUN npm run build

FROM rocm/dev-ubuntu-24.04:7.2.1-complete AS translator_asr_builder

ENV DEBIAN_FRONTEND=noninteractive
ENV UV_INSTALL_DIR=/usr/local/bin
ENV UV_CACHE_DIR=/root/.cache/uv

COPY --from=astral/uv:latest /uv /usr/local/bin/uv

RUN apt-get update && \
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    libsndfile1 \
    python3.12 \
    python3.12-venv \
    unzip \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /build/translator/asr
COPY translator/asr/ ./
RUN chmod +x ./setup.sh && ./setup.sh

FROM python:3.13-bookworm AS app_python_builder

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_CACHE_DIR=/root/.cache/pip
ENV UV_CACHE_DIR=/root/.cache/uv
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_INSTALL_DIR=/usr/bin

COPY --from=astral/uv:latest /uv /usr/bin/

WORKDIR /opt/

COPY ./pyproject.toml ./uv.lock ./
RUN --mount=type=cache,target=/root/.cache/pip,id=pip-cache \
  --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
  uv venv --python /usr/local/bin/python3 --system-site-packages --relocatable ./python && \
  VIRTUAL_ENV=/opt/python uv sync --no-dev --link-mode=copy --active

FROM rocm/dev-ubuntu-24.04:7.2.1-complete

ARG TZ=UTC
ARG USER_ID=1000
ARG DEBIAN_FRONTEND=noninteractive

ENV IN_CONTAINER=1
ENV UMASK=0002
ENV YTP_CONFIG_PATH=/config
ENV YTP_TEMP_PATH=/tmp
ENV YTP_DOWNLOAD_PATH=/downloads
ENV YTP_PORT=8081
ENV YTP_TRANSLATOR_PROJECT_PATH=/app/translator
ENV YTP_TRANSLATOR_PYTHON_EXE=/app/translator/asr/.venv/bin/python
ENV YTP_TRANSLATOR_UV_EXE=/usr/local/bin/uv
ENV XDG_CONFIG_HOME=/config
ENV XDG_CACHE_HOME=/tmp
ENV PYDEVD_DISABLE_FILE_VALIDATION=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONFAULTHANDLER=1
ENV PATH="/opt/bin:/opt/python/bin:/usr/local/bin:$PATH"
ENV HOME=/app
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

COPY --from=astral/uv:latest /uv /usr/local/bin/uv
COPY --from=translator_node_builder /usr/local/ /usr/local/
COPY --from=app_python_builder /usr/local/ /usr/local/

RUN install -d -m 0775 -o ${USER_ID} -g 0 /app /config /downloads && \
  ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime && \
  echo ${TZ} > /etc/timezone && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    aria2 \
    bash \
    ca-certificates \
    curl \
    file \
    git \
    libmagic1 \
    libsndfile1 \
    locales \
    mkvtoolnix \
    patch \
    procps \
    python3 \
    python3-venv \
    sqlite3 \
    tzdata \
    vainfo \
    xz-utils \
  && sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
  && dpkg-reconfigure --frontend=noninteractive locales \
  && update-locale LANG=en_US.UTF-8 \
  && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /
COPY --chown=${USER_ID}:0 yt-dlp /opt/bin/yt-dlp
COPY --chown=${USER_ID}:0 ./app /app/app
COPY --chown=${USER_ID}:0 ./translator /app/translator
COPY --chown=${USER_ID}:0 --from=ui_builder /app/exported /app/ui/exported
COPY --chown=${USER_ID}:0 --from=app_python_builder /opt/python /opt/python
COPY --chown=${USER_ID}:0 --from=translator_node_builder /build/translator/node_modules /app/translator/node_modules
COPY --chown=${USER_ID}:0 --from=translator_node_builder /build/translator/dist /app/translator/dist
# The qwen_env venv is deduplicated in setup.sh: its heavy ROCm packages are symlinked
# back to the main ASR env so exporting the image does not materialize a second Torch stack.
COPY --chown=${USER_ID}:0 --from=translator_asr_builder /build/translator/asr/.venv /app/translator/asr/.venv
COPY --chown=${USER_ID}:0 --from=translator_asr_builder /build/translator/asr/qwen_env/.venv /app/translator/asr/qwen_env/.venv
COPY --from=ghcr.io/arabcoders/alpine-mp4box /usr/bin/mp4box /usr/bin/mp4box
COPY --from=ghcr.io/arabcoders/jellyfin-ffmpeg /usr/bin/ffmpeg /usr/bin/ffmpeg
COPY --from=ghcr.io/arabcoders/jellyfin-ffmpeg /usr/bin/ffprobe /usr/bin/ffprobe
COPY --from=denoland/deno:latest /usr/bin/deno /usr/bin/deno
COPY --chown=${USER_ID}:0 ./healthcheck.sh /usr/local/bin/healthcheck

RUN sed -i 's/\r$//g' /entrypoint.sh && chmod +x /entrypoint.sh && \
  chmod +x /usr/local/bin/healthcheck /usr/bin/mp4box /usr/bin/ffmpeg /usr/bin/ffprobe /usr/bin/deno /opt/bin/yt-dlp

VOLUME /config
VOLUME /downloads

EXPOSE 8081

USER ${USER_ID}

WORKDIR /tmp

HEALTHCHECK --interval=10s --timeout=20s --start-period=60s --retries=3 CMD [ "/usr/local/bin/healthcheck" ]

ENTRYPOINT ["/entrypoint.sh"]

CMD ["/opt/python/bin/python", "/app/app/main.py", "--ytp-process"]
