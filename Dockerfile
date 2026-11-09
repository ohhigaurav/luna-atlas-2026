FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend
WORKDIR /app

# The rasterio/GDAL wheels expect the system Expat library (libexpat.so.1); python:3.13-slim does not ship it,
# and without it every terrain answer fails ("libexpat.so.1: cannot open shared object file").
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt
COPY backend /app/backend
COPY frontend /app/frontend
COPY data /app/data
COPY docs /app/docs
COPY LICENSE NOTICE.md README.md /app/

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/live', timeout=3)" || exit 1
CMD ["uvicorn", "lunar_core.api:app", "--host", "0.0.0.0", "--port", "8000"]
