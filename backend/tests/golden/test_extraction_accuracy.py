"""抽取準確度的回歸閘門。

跑法：
    .venv/Scripts/python -m pytest backend/tests/golden -s

`-s` 會印出逐案例的表格，以及每一筆漏抽／亂抽的實際字串——那就是「下一步該去補
哪張表」的清單。

怎麼用這個閘門：
    1. 補標註（data/golden_set/，格式見該目錄的 README.md）
    2. 跑一次，看漏抽／亂抽是什麼
    3. 改 data/alias_dictionary.json 或 extractors/rule_engine.py 的三張表
    4. 再跑，數字要往上
    5. 把下面的 BASELINE 調到新的數字——這樣「有沒有變好」是 diff 裡看得見的一行

門檻是棘輪，但要分清楚兩種情況：

  改抽取規則   -> 數字只能往上。調降門檻等於默認抽取變差了，那應該是一個被討論
                  的決定，不是為了讓測試變綠順手改掉的數字。
  新增標註案例 -> 門檻可以跟著變（樣本變了，數字本來就會動），但**要跟新案例在
                  同一個 commit**，這樣 diff 看得出來是「多了樣本」而不是「品質退步」。
"""

import pytest

from app.core.config import settings
from app.extractors import ExtractionPipeline
from tests.golden.scoring import aggregate, format_report, load_cases, score_case

GOLDEN_DIR = settings.DATA_DIR / "golden_set"

# 2026-09-11 實測值：7 個案例、38 筆標註，漏抽 1、亂抽 5。
#
# 門檻從 100%/100% 降下來**不是品質退步**，是樣本擴充：新增了 sample-05／06 兩份
# 真實文件（+18 筆標註），它們暴露出既有的抽取缺口。修完當下的數字就是這裡的門檻。
#
# 這個 golden set 至今抓出 10 個抽取 bug（說明都在 tests/unit/test_extractors.py）：
#   2026-09-10  合成範例  日常用語被當法規名、法規「編」層級被截短      94%/88% -> 100%/100%
#   2026-09-11  真實文件  \b 在中文後失效、引號卡住條號、引號內容不驗證、
#                         「國家標準」泛稱                               90%/86% -> 100%/100%
#   2026-09-11  真實文件  句子片段被當名稱（一次七筆）、括號切一半、
#                         「相關法」「技術法」半截詞                      70%/86% -> 97%/88%
#
# 已知缺口（都有標註釘著，修好數字自然會往上）：
#   亂抽 5 筆  承攬廠商自有文件（品質管理標準、作業標準…）。這類要靠「交付文件完備性」
#              那條線處理，不是靠黑名單硬擋——設計討論中。
#   漏抽 1 筆  「公有建築物施工階段契約約定權責分工表」字尾「表」不在識別清單。
#   條號錯     標準的「第N項」抓不到（CNS 3090 第7項），不計入 P/R。
BASELINE_RECALL = 0.97     # 37/38
BASELINE_PRECISION = 0.88  # 37/42



@pytest.fixture(scope="module")
def cases():
    if not GOLDEN_DIR.exists():
        pytest.fail(f"找不到 golden set 目錄：{GOLDEN_DIR}")
    return load_cases(GOLDEN_DIR)


async def test_extraction_accuracy_does_not_regress(cases, capsys):
    # AI 關閉（conftest 設定），所以只量規則與字典兩層，結果是確定性的
    pipeline = ExtractionPipeline(llm_provider=None)

    scores = []
    for case in cases:
        candidates, _ = await pipeline.extract(case.text)
        scores.append(score_case(case, candidates))

    totals = aggregate(scores)
    with capsys.disabled():
        print(format_report(scores))

    # 空的 golden set 不能算通過——沒有標註卻報「沒有退步」是假訊號
    assert totals.expected_count > 0, "golden set 是空的，沒有任何東西被量到"

    assert totals.recall >= BASELINE_RECALL, (
        f"漏抽變多了：recall {totals.recall:.1%} < 基準 {BASELINE_RECALL:.1%}"
    )
    assert totals.precision >= BASELINE_PRECISION, (
        f"亂抽變多了：precision {totals.precision:.1%} < 基準 {BASELINE_PRECISION:.1%}"
    )
