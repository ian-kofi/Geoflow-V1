# Hugging Face Space for GeoFlow: builds the app from the GitHub repository.
# To update the demo after pushing to GitHub: Space settings → "Factory rebuild".

# ---- Source + frontend build -----------------------------------------------
FROM node:22 AS web
ARG REPO=https://github.com/ian-kofi/Geoflow-V1.git
ARG REF=main
RUN git clone --depth 1 --branch "$REF" "$REPO" /src
WORKDIR /src/geoflow-project
RUN npm ci && VITE_API_URL=same-origin npm run build

# ---- Backend + app ---------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GEOFLOW_STATIC_DIR=/app/static \
    GEOFLOW_MAX_UPLOAD_MB=50 \
    GEOFLOW_MAX_JOBS=3 \
    GEOFLOW_RETENTION_HOURS=6 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN useradd --create-home --uid 1000 geoflow
WORKDIR /app/backend
COPY --from=web /src/geoflow-backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY --from=web --chown=geoflow /src/geoflow-backend/ ./
COPY --from=web --chown=geoflow /src/geoflow-project/dist /app/static
RUN mkdir -p outputs files uploads cache && chown -R geoflow /app

USER geoflow
EXPOSE 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
