FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
# Networked builds must use the managed environment's supplied CA secret.
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
RUN useradd --create-home --uid 10001 app && mkdir -p /app/runtime && chown app:app /app/runtime
COPY --chown=app:app . .
USER app
EXPOSE 8080
CMD ["python", "bot.py"]
