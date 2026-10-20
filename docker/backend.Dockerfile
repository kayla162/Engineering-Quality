FROM python:3.12-slim

# Opt in explicitly: docker compose build --build-arg INSTALL_OCR=true backend
ARG INSTALL_OCR=false

# fonts-arphic-uming: PDF 匯出需要的繁體中文字型（見 backend/app/reports/fonts.py）
#   注意：不要換成 fonts-noto-cjk。Noto CJK 是 OpenType/CFF 字型，
#   reportlab 只吃 TrueType 外框，載入會失敗。
# curl: docker-compose healthcheck 用
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-arphic-uming curl \
    && rm -rf /var/lib/apt/lists/*

# RapidOCR uses ONNX Runtime and OpenCV. Keep their Linux runtime libraries
# out of the default image; no model/API download occurs at application startup.
RUN case "$INSTALL_OCR" in \
      true) apt-get update \
        && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
        && rm -rf /var/lib/apt/lists/* ;; \
      false) ;; \
      *) echo "INSTALL_OCR must be true or false" >&2; exit 1 ;; \
    esac

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/backend

WORKDIR /app

COPY requirements.txt requirements-ocr.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_OCR" = "true" ]; then \
         pip install --no-cache-dir -r requirements-ocr.txt; \
       fi

COPY backend/ ./backend/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY alembic.ini ./

# 啟動時先跑 migration + 種子資料，再啟動服務
COPY docker/entrypoint.sh ./docker/entrypoint.sh
RUN chmod +x ./docker/entrypoint.sh

EXPOSE 8000
CMD ["./docker/entrypoint.sh"]
