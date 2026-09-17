"""PDF 用的中文字型解析。

reportlab 內建的 CID 字型（MSung-Light 等）在多數檢視器上會顯示成亂碼，
所以這裡改成嵌入一個真正的 TrueType 中文字型。

尋找順序：
1. settings.PDF_FONT_PATH（在 .env 指定）
2. 下方 _CANDIDATES 列出的常見系統字型路徑（Linux 容器 / Windows / macOS）

都找不到就丟出明確的錯誤，而不是安靜地輸出一份看不懂的 PDF。
Docker 映像檔已在 docker/backend.Dockerfile 安裝 fonts-arphic-uming。

重要：字型必須是 TrueType 外框。Noto CJK（NotoSansCJK-*.ttc）是 OpenType/CFF，
reportlab 載不進去，所以候選清單把 TrueType 的字型排在前面。
"""

import logging
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

FONT_NAME = "ReportCJK"

_CANDIDATES: tuple[str, ...] = (
    # Linux（Docker 映像檔安裝的是 fonts-arphic-uming）
    "/usr/share/fonts/truetype/arphic/uming.ttc",
    "/usr/share/fonts/truetype/arphic/ukai.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    # Windows（繁體中文優先）
    "C:/Windows/Fonts/msjh.ttc",
    "C:/Windows/Fonts/mingliu.ttc",
    "C:/Windows/Fonts/kaiu.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
)

_registered = False


def _paths() -> list[Path]:
    paths = [Path(settings.PDF_FONT_PATH)] if settings.PDF_FONT_PATH else []
    return paths + [Path(candidate) for candidate in _CANDIDATES]


def ensure_font() -> str:
    """註冊中文字型並回傳字型名稱。找不到字型時丟出可讀的錯誤。"""
    global _registered
    if _registered:
        return FONT_NAME

    for path in _paths():
        if not path.exists():
            continue
        try:
            # .ttc 是字型集合，取第一個字面
            index = 0 if path.suffix.lower() == ".ttc" else None
            font = (
                TTFont(FONT_NAME, str(path), subfontIndex=index)
                if index is not None
                else TTFont(FONT_NAME, str(path))
            )
            pdfmetrics.registerFont(font)
            _registered = True
            logger.info("PDF 中文字型：%s", path)
            return FONT_NAME
        except Exception as exc:
            logger.warning("字型無法載入，改試下一個：%s（%s）", path, exc)

    raise AppError(
        "PDF 匯出需要中文字型，但系統找不到可用的字型。"
        "請安裝 TrueType 中文字型（Linux：apt-get install fonts-arphic-uming），"
        "或在 .env 設定 PDF_FONT_PATH 指向 .ttf/.ttc 檔案。"
        "（Excel 與 CSV 匯出不受影響）"
    )
