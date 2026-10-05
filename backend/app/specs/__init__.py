"""施工規範書：把一份規範書切成章節，並定位每一章宣告的依據。

和 `workitems/` 的關係：那裡從標單建出工項，這裡從規範書建出依據來源，
兩者靠計價代碼前 5 碼 = 施工綱要規範章碼接起來。

和 `sources/pcces_source.py` 的關係（容易混淆，特別注意）：
    pcces_source 是**全國共通**的綱要規範目錄（315 章），只給章名。
    這裡處理的是**本案**的規範書（實測 86 章），給實際條文。
    兩者的落差就是檢核結果「本案規範未收錄」——不要把它們當成同一份資料。
"""

from app.specs.chapter_reader import SpecChapterRow, SpecFormatError, read_spec_chapters

__all__ = ["SpecChapterRow", "SpecFormatError", "read_spec_chapters"]
