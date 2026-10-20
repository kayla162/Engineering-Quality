"""選配本機 OCR。只處理圖框，不解讀結構、安全性或工法。"""
from app.core.errors import AppError


class LocalOCR:
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise AppError("未安裝本機 OCR，請安裝 requirements-ocr.txt，或取消 OCR 後人工補登") from exc
        self.engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2, max_side_len=4200)

    def __call__(self, page):
        import numpy as np
        import pymupdf
        # Pixmap coordinates use displayed page rotation; title-block spans use the same space.
        scale = min(3.5, 3800 / max(page.rect.width, 1))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
        pixels = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        top = int(pix.height * .86)
        result, _ = self.engine(pixels[top:, :, :3], use_cls=True)
        spans = []
        for box, text, confidence in result or []:
            if float(confidence) < .70:
                continue
            xs, ys = zip(*box)
            spans.append((min(xs) / scale, (min(ys) + top) / scale,
                          max(xs) / scale, (max(ys) + top) / scale, text))
        return spans
