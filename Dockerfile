FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501

WORKDIR /app

RUN groupadd --gid 10001 retailflow \
    && useradd --uid 10001 --gid retailflow --create-home --shell /usr/sbin/nologin retailflow

# Install third-party dependencies in a cacheable layer before application sources.
COPY pyproject.toml README.md LICENSE ./
RUN python -c "import pathlib, tomllib; metadata = tomllib.loads(pathlib.Path('pyproject.toml').read_text()); pathlib.Path('/tmp/requirements.txt').write_text('\\n'.join(metadata['project']['dependencies']) + '\\n')" \
    && python -m pip install --upgrade pip \
    && python -m pip install --requirement /tmp/requirements.txt

COPY src ./src
RUN python -m pip install --no-deps .

COPY app ./app
COPY config ./config
COPY mock_api ./mock_api
COPY scripts ./scripts
COPY docker ./docker

RUN mkdir -p /app/output /app/data /app/demo_data \
    && chmod 0755 /app/docker/entrypoint.sh \
    && chown -R retailflow:retailflow /app/output /app/data /app/demo_data /home/retailflow

USER retailflow

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).read()"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["python", "-m", "streamlit", "run", "app/main.py"]
