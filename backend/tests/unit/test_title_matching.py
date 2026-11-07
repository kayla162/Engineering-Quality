"""圖名和工項比對：圖名拆成主體（drawing_reader.title_subjects），OCR 錯字用本案標單用詞校正（title_vocabulary）。

案例取自秀山真實契約圖讀到的圖名與真實標單的分項名稱。
"""

from app.specs.drawing_reader import is_related, title_subjects
from app.specs.title_vocabulary import correct_title, vocabulary


def test_a_title_is_split_into_what_it_shows():
    assert title_subjects("一層平面圖(排水配置)") == ["排水"]
    assert title_subjects("二層配置圖電信,資訊網路及電視設備") == ["電信", "資訊網路", "電視"]
    assert title_subjects("三層至四層結構平面圖") == ["結構"]
    assert title_subjects("屋突一層平面圖(避雷針配置)") == ["避雷針"]
    # 索引頁的泛稱不算主體
    assert title_subjects("索引表.工程概要及內容,圖例.位置圖") == []
    # 中文字不到兩個的不算：「(2m)」不能對到「標稱52mm」
    assert title_subjects("(2m)es/屋突頂平面圖") == []


def test_a_floor_prefixed_title_matches_by_its_subjects():
    """主體開頭是「一層」時，舊規則對不到；拆出來的段整段出現在工項名稱裡就算。"""
    assert is_related("污排水PVC管設備", "一層平面圖(排水配置)")
    assert is_related("資訊網路系統配管線及設備工程", "二層配置圖電信,資訊網路及電視設備")
    assert not is_related("裝修工程", "索引表.工程概要及內容,圖例.位置圖")
    assert not is_related("產品，導線管，E管，標稱52mm", "(2m)es/屋突頂平面圖")


def test_notes_in_an_item_name_are_not_matched():
    """分項名稱括號裡的附註提到「插座」，不代表櫥櫃畫在插座配置圖上。"""
    section = "搗擺及櫥櫃工程(櫥櫃應配合機電圖說留設櫃身.踢腳.檯面板上方牆面出線口插座面板)"
    assert not is_related(section, "一層動力.插座配置平面圖")


def test_the_old_subject_rule_still_applies():
    assert is_related("模板，組立", "模板組立詳圖")
    assert not is_related("鋼筋，含加工及組立", "模板組立詳圖")


VOCAB = vocabulary([
    "安全監控錄影、影視對講、門禁管制系統配管線及設備工程",
    "勤務指示燈,LED計時器系統配管線及設備工程",
    "LED字幕機設備工程",
    "插座配置",
    "二層平面",
])


def test_ocr_typos_are_corrected_from_the_project_vocabulary():
    assert correct_title("安全監視暨緊急求救/影視對讚/勤蕩指示燈", VOCAB) == "安全監視暨緊急求救/影視對講/勤務指示燈"
    assert correct_title("一層動力.插座芝置平面圖", VOCAB) == "一層動力.插座配置平面圖"


def test_numbers_and_common_characters_are_not_corrected():
    """「三層平面」和詞彙裡的「二層平面」只差一個字，但數字不換。"""
    assert correct_title("三層平面圖", VOCAB) == "三層平面圖"
    # 「設備」的「設」在詞彙裡很常見，不當成錯字
    assert correct_title("緊急照明設備", VOCAB) == "緊急照明設備"


def test_an_ambiguous_correction_is_not_made():
    vocab = vocabulary(["給水管線", "排水管線"])
    # 「污水管線」離「給水管線」「排水管線」都只差一個字：分不出來，不改
    assert correct_title("污水管線", vocab) == "污水管線"


def test_three_character_windows_are_not_corrected():
    """三個字只差一個字的證據太弱：「辦公桌」不能因為詞彙有「辦公室」就被改掉（秀山建築圖實測）。"""
    assert correct_title("辦公桌詳圖", vocabulary(["辦公室"])) == "辦公桌詳圖"


def test_finishes_are_shown_on_the_finishes_plans():
    """粉刷、貼磚畫在飾材配置圖上，工項名稱沒有「飾材」；鋼構的防鏽油漆不算。"""
    assert is_related("水泥漆，內牆1:3水泥粉光刷綠建材水性水泥漆", "三層平面圖(地坪及牆面飾材配置圖)")
    assert is_related("鋪貼壁磚，內牆打底貼30*30cm霧面石英磚", "一樓夾層平面圖(地坪及牆面飾材配置圖)")
    assert is_related("油漆，踢腳批土+油漆踢腳(H=10cm)", "二層平面(天花飾材配置圖)")
    assert not is_related("鋼構防鏽油漆", "三層平面圖(地坪及牆面飾材配置圖)")


def test_fire_equipment_is_shown_on_the_fire_drawings():
    assert is_related("滅火器及火警自動警報設備設備", "數量表,消防設備設置說明")
    assert is_related("避難方向指示燈,C級 標示面板 1:1", "一層平面圖消防設備平面圖")
    assert not is_related("滅火器及火警自動警報設備設備", "一層平面圖(排水配置)")


def test_grounding_and_lightning_items_are_shown_on_the_lightning_drawings():
    assert is_related("接地避雷設備工程", "二層平面圖(避雷針配置)")
    assert is_related("產品，接地導線，硬裸銅絞電線，標稱截面積100mm2", "電避雷針詳圖")
    assert is_related("雷擊計數器需含脈衝輸出-LED顯示功能(IP68)", "屋頂層平面圖(避雷針配置)")
    assert not is_related("接地避雷設備工程", "一層平面圖(排水配置)")


def test_antenna_fire_stopping_and_partitions_are_shown_on_their_drawings():
    assert is_related("數位天線系統配管線及設備工程", "一層平面圖配置圖電信資訊網路及電視設備")
    assert is_related("膨脹型防火泥(5加崙)", "屋突一層平面圖防火阻絕")
    assert is_related("UL防火等級岩棉(須符合UL1479)", "防火阻絕設施詳圖")
    assert not is_related("半明架岩棉天花板", "防火阻絕設施詳圖")
    assert is_related("一般輕質灌漿輕隔間牆(具2小時防火時效)", "濕式灌漿輕隔間牆詳圖")
