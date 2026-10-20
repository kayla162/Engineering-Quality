"""Offline drawing index. Outputs stay local; no source PDF is copied or uploaded."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.drawings.reader import read_drawings
from app.drawings.ocr import LocalOCR


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def progress(current, total):
        if current == 1 or current % 25 == 0 or current == total:
            print(f"pages {current}/{total}", flush=True)
    rows = read_drawings(args.pdf, ocr=LocalOCR() if args.ocr else None, progress=progress)
    counts = Counter(r.number for r in rows if r.number)
    summary = {
        "pages": len(rows), "with_number": sum(bool(r.number) for r in rows),
        "with_title": sum(bool(r.title) for r in rows),
        "complete_title_blocks": sum(bool(r.number and r.title) for r in rows),
        "duplicate_numbers": sum(n > 1 for n in counts.values()),
        "warning_pages": sum(bool(r.warning) for r in rows),
        "methods": dict(Counter(r.method for r in rows)),
    }
    args.output.write_text(json.dumps({"summary": summary, "sheets": [asdict(r) for r in rows]},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
