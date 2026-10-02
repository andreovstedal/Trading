# One image for the web app and every collector job. Railway builds it from the
# repository; the cron services override the start command (see .railway/railway.ts).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install . && useradd --create-home app

USER app
# The web app listens on $PORT, which Railway sets.
CMD ["nordic-signals", "web", "--host", "0.0.0.0"]
