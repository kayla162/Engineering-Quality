#!/bin/sh
# 後端容器的啟動流程：建表 -> 同步法規 -> 載入種子資料 -> 啟動服務
set -e

echo "[entrypoint] 執行資料庫 migration..."
alembic upgrade head

# 只有啟用 taiwan_law 且索引還不存在時才同步，避免每次啟動都下載 31MB。
# 索引放在 volume（見 docker-compose.yml 的 lawindex），重建映像檔不會消失。
INDEX_PATH="${TAIWAN_LAW_INDEX_PATH:-/app/data/taiwan_law_index.json}"
case "${REGULATION_SOURCES:-mock}" in
  *taiwan_law*)
    if [ -f "$INDEX_PATH" ]; then
      echo "[entrypoint] 全國法規資料庫索引已存在，略過同步：$INDEX_PATH"
    else
      echo "[entrypoint] 首次啟動，同步全國法規資料庫（約 31MB，需要對外網路）..."
      if ! python scripts/sync_taiwan_law.py --output "$INDEX_PATH"; then
        echo "[entrypoint] 同步失敗，先繼續啟動。"
        echo "[entrypoint] 之後可執行：docker compose exec backend python scripts/sync_taiwan_law.py --output $INDEX_PATH"
      fi
    fi
    ;;
esac

# 施工綱要規範目錄只有幾十 KB，但一樣只在首次啟動同步，避免每次重啟都打工程會的站。
PCCES_PATH="${PCCES_INDEX_PATH:-/app/data/pcces_index.json}"
case "${REGULATION_SOURCES:-mock}" in
  *pcces*)
    if [ -f "$PCCES_PATH" ]; then
      echo "[entrypoint] 施工綱要規範目錄已存在，略過同步：$PCCES_PATH"
    else
      echo "[entrypoint] 首次啟動，同步公共工程施工綱要規範目錄（315 章，需要對外網路）..."
      if ! python scripts/sync_pcces.py --output "$PCCES_PATH"; then
        echo "[entrypoint] 同步失敗，先繼續啟動（前端會顯示來源未就緒）。"
        echo "[entrypoint] 之後可執行：docker compose exec backend python scripts/sync_pcces.py --output $PCCES_PATH"
      fi
    fi
    ;;
esac

echo "[entrypoint] 載入種子資料（別名字典；啟用 mock 時另含假法規）..."
python scripts/seed_data.py

echo "[entrypoint] 啟動 API..."
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
