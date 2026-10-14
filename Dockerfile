# GeoFlow as one container: the FastAPI backend also serves the built React app.
#   docker build -t geoflow .
#   docker run -p 7860:7860 -e GEOFLOW_BASE_URL=http://localhost:7860 geoflow
# then open http://localhost:7860

# ---- Frontend build --------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY geoflow-project/package.json geoflow-project/package-lock.json ./
RUN npm ci
COPY geoflow-project/ ./
RUN VITE_API_URL=same-origin npm run build

# ---- Backend + app ---------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GEOFLOW_STATIC_DIR=/app/static \
    GEOFLOW_MAX_UPLOAD_MB=50 \
    GEOFLOW_MAX_JOBS=3 \
    GEOFLOW_RETENTION_HOURS=6 \
    MPLCONFIGDIR=/tmp/matplotlib

# Runs as a non-root user (uid 1000, as Hugging Face Spaces expects)
RUN useradd --create-home --uid 1000 geoflow
WORKDIR /app/backend
COPY geoflow-backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY --chown=geoflow geoflow-backend/ ./
COPY --from=web --chown=geoflow /web/dist /app/static
RUN mkdir -p outputs files uploads cache && chown -R geoflow /app

USER geoflow
EXPOSE 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
