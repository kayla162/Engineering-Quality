"""工項：從標單建立專案的工作項目清單。

和 `parsers/` 的分工：`parsers/` 把檔案變成給法規抽取用的文字段落，
這裡走同一個 `parsers/workbook.py` 讀同一份檔，但要的是保留欄位位置的結構化資料
（第幾欄是項次、第幾欄是計價代碼）。
"""

from app.workitems.boq_reader import BoqFormatError, BoqRow, read_boq

__all__ = ["BoqFormatError", "BoqRow", "read_boq"]
