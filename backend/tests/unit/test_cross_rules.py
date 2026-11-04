"""法規雙重規範提醒：同一個構件要同時滿足兩部以上規定（邏輯圖：頂樓 RC 欄杆要 1.1m，超過 1.5m 會被納入樓高）。

目錄 data/cross_rules.json 是示範：只有使用者給的那一條有出處，其餘條號與數值未查證，每筆寫明。
"""

from app.specs.cross_rules import load_cross_rules, remind


def test_every_rule_states_where_it_came_from():
    rules = load_cross_rules()
    assert rules and all(rule["provenance"] for rule in rules)
    assert any("使用者提供" in rule["provenance"] for rule in rules)


def test_a_boq_item_triggers_the_rule_and_is_quoted():
    texts = [
        ("標單", "壹.一.1.4.20 露台.屋頂沿女兒牆及外牆側壓簷施工"),
        ("標單", "壹.一.1.3.1 鋼筋，SD420W"),
    ]
    (reminder,) = remind(texts)
    assert reminder.title == "屋頂欄杆、女兒牆的高度"
    assert reminder.evidence == ["標單：壹.一.1.4.20 露台.屋頂沿女兒牆及外牆側壓簷施工"]
    assert "1.5m" in reminder.note


def test_drawing_titles_trigger_too_and_evidence_is_capped():
    texts = [("契約圖", f"E{i}-01 一層電梯平面圖") for i in range(6)]
    (reminder,) = remind(texts)
    assert reminder.title == "電梯同時是無障礙昇降機"
    assert len(reminder.evidence) == 3
    assert reminder.matches == 6


def test_nothing_triggered_means_no_reminders():
    assert remind([("標單", "壹.一.1.3.1 鋼筋，SD420W")]) == []
