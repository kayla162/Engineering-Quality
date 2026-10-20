"""以標題欄座標讀取圖號、圖名，不把內文引用或目錄當成本頁圖號。"""
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pymupdf

from app.core.errors import UnprocessableDocumentError

Span = tuple[float, float, float, float, str]
NUMBER = re.compile(r"(?<![A-Z0-9-])(?:[A-Z]{1,3}\d{0,2})-\d{2,3}[A-Z]?(?:-\d{1,2}[A-Z]?)?(?![A-Z0-9-])")
# Title-derived disciplines are candidates, never asserted BOQ line items.
ITEM_WORDS = ("鋼筋", "混凝土", "防水", "模板", "開挖", "基樁", "門窗", "門檻",
              "天花", "輕隔間", "帷幕牆", "電梯", "欄杆", "扶手", "油漆", "磁磚",
              "排水", "避雷", "景觀", "擋土", "鋼構", "地坪", "百葉", "防火門")
ITEM_ALIASES = {"鋼筋": ("配筋",), "鋼構": ("鋼結構",)}


@dataclass
class DrawingPage:
    page: int
    number: str | None
    title: str | None
    method: str
    evidence: str
    warning: str | None


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


def item_names(title: str | None) -> list[str]:
    text = compact(title or "")
    return [word for word in ITEM_WORDS
            if any(term in text for term in (word, *ITEM_ALIASES.get(word, ())))]


def title_block(spans: list[Span], height: float) -> tuple[str | None, str | None, str]:
    # Only the bottom title block. Drawing indexes may contain hundreds of references.
    bottom = [s for s in spans if s[1] >= height * .72]
    title_anchors = [s for s in bottom if compact(s[4]) in {"DRAWINGTITLE", "圖名"}]
    # Narrow OCR label variants; never substitute guessed digits in the value.
    number_labels = {"DRG.NO", "DRG.ND", "圖號", "图号", "图號"}
    number_anchors = [s for s in bottom if compact(s[4]).rstrip(".:：") in number_labels]
    metadata_labels = number_labels | {
        "圖名", "DRAWINGTITLE", "張數", "張数", "张数", "SHEETNO", "版次",
        "VER", "比例", "SCALE", "單位", "单位", "UNIT", "日期", "DATE",
    }
    numbers: set[str] = set()
    for a in number_anchors:
        for s in bottom:
            # Value is beside the label, on either of its bilingual baselines.
            if a[0] <= s[0] <= a[0] + height * .20 and abs(s[1] - a[1]) < height * .035:
                numbers.update(NUMBER.findall(compact(s[4])))
    titles: set[str] = set()
    for a in title_anchors:
        center = (a[0] + a[2]) / 2
        candidates = []
        for s in bottom:
            text = s[4].strip()
            if (s[1] > a[3] and s[1] < a[3] + height * .07
                    and abs((s[0] + s[2]) / 2 - center) < height * .16
                    and not NUMBER.fullmatch(compact(text))
                    and compact(text).rstrip(".:：") not in metadata_labels
                    and not re.fullmatch(r"[\d\s:：./-]+", text)):
                candidates.append(s)
        if candidates:
            # Prefer the title band; some PDFs misplace the title onto the
            # number row. Only fall back there after excluding metadata labels.
            above_number = [s for s in candidates if not number_anchors
                            or s[1] < min(n[1] for n in number_anchors)]
            candidates = above_number or candidates
            # The first text row below the bilingual title anchor is the title.
            # Metadata labels further down (SHEET NO., VER.) are not extra titles.
            first_y = min(s[1] for s in candidates)
            line = sorted((s for s in candidates if abs(s[1] - first_y) < height * .008),
                          key=lambda s: s[0])
            titles.add(" ".join(s[4].strip() for s in line))
    title = next(iter(titles)) if len(titles) == 1 else None
    number = next(iter(numbers)) if len(numbers) == 1 else None
    evidence = "\n".join(s[4] for s in sorted(bottom, key=lambda s: (s[1], s[0])))[:6000]
    return number, title, evidence


def text_spans(page) -> list[Span]:
    spans = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                rect = pymupdf.Rect(span["bbox"]) * page.rotation_matrix
                spans.append((*rect, span["text"]))
    return spans


def read_drawings(path: Path, ocr: Callable | None = None,
                  progress: Callable[[int, int], None] | None = None) -> list[DrawingPage]:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise UnprocessableDocumentError("無法開啟圖說 PDF") from exc
    with doc:
        if doc.needs_pass:
            raise UnprocessableDocumentError("圖說 PDF 已加密")
        rows = []
        for index, page in enumerate(doc):
            spans = text_spans(page)
            number, title, evidence = title_block(spans, page.rect.height)
            method = "text" if spans else "unreadable"
            warnings = []
            if (not number or not title) and ocr:
                # OCR replaces the whole title block; do not silently combine two readings.
                number, title, evidence = title_block(ocr(page), page.rect.height)
                method = "ocr"
                warnings.append("OCR 辨識結果尚待人工核對")
            if not number or not title:
                warnings.append("圖號或圖名未可靠讀取，請核對原圖或人工補登")
            if not spans and not ocr:
                warnings.append("本頁沒有文字層，尚未執行 OCR")
            rows.append(DrawingPage(index + 1, number, title, method, evidence,
                                    "；".join(warnings) or None))
            if progress:
                progress(index + 1, len(doc))
        return rows
