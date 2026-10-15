"""依據的法規查證：只採完全同名。

為什麼不用模糊比對（2026-10-15 對全國法規索引實測）：

    低電壓金屬閉鎖型配電箱檢驗法 -> 商品檢驗法、民法、醫事檢驗師法
    屋內線路裝置規則            -> 中央空氣調節系統電表及線路裝置規則、兵籍規則
    檢查辦法                    -> 交通部會計檢查辦法、傳染病危險群及特定對象檢查辦法

一個 CNS 配電箱檢驗方法的最佳候選是民法。採用它就是 pcces_source.py 開頭
描述的那種「有信心的錯」，而且因為欄位填滿了，比留白更難被發現。

查不到完全同名的名稱**不會出現在回傳值裡**，呼叫端據此標成「未查證」。
那和「查無此法規」是兩件事：屋內線路裝置規則（實測 129 筆依據）與
建築技術規則（17 筆）都是真的法規，只是不以那個名稱登錄在索引裡
（建築技術規則在索引中拆成建築構造編、建築設備編等四編）。
"""

import logging

from app.core.errors import SourceQueryError
from app.core.logging import log_context

logger = logging.getLogger(__name__)


async def verify_names(names: set[str], source) -> dict[str, str]:
    """把名稱拿去法規來源查完全同名的狀態。

    回傳只含查得到的；查不到的不在 dict 裡。來源掛掉時回空 dict——
    檢核表沒有查證狀態仍然有價值，不該因為外部來源壞掉就整張產不出來。
    """
    statuses: dict[str, str] = {}
    for name in sorted(names):
        try:
            results = await source.search(name)
        except SourceQueryError as exc:
            logger.warning(
                "法規查證來源查詢失敗，整批跳過",
                extra=log_context(name=name, detail=str(exc)),
            )
            return {}
        for result in results:
            if result.name == name:
                statuses[name] = result.status
                break
    return statuses
