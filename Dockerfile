# One image for every collector job (and later the web app). Railway builds it
# from the repository; each service chooses what to run with its start command
# (see .railway/railway.ts).
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
CMD ["nordic-signals", "status"]
