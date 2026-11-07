"""混合檢索：條號比對、RRF 合併、三種模式（app/search/hybrid.py、corpus.py）。

向量用假的 embedder（依關鍵概念給固定方向），不需要 torch。
"""

import io
import json
import zipfile

import numpy as np
import pytest

from app.search.corpus import Chunk, law_articles, spec_chapters
from app.search.hybrid import InMemoryIndex, RefMatcher, cn_to_int, fuse


def article(law: str, number: str, content: str, heading: str = "") -> Chunk:
    return Chunk(f"{law} 第 {number} 條", "law_article", law, f"第 {number} 條", heading, content)


CHUNKS = [
    article("建築法", "34", "主管建築機關審查建築物工程圖樣及說明書"),
    article("建築法", "69", "建築物在施工中，鄰接其他建築物施行挖土工程時，應作防護其傾斜或倒壞之措施"),
    article("營造業法", "30", "營造業承攬一定金額以上之工程，應於工地置工地主任"),
    article("營造業法施行細則", "18", "本法第三十條所定應置工地主任之工程金額"),
    article("政府採購法", "22", "機關辦理公告金額以上之採購，得採限制性招標"),
    article("政府採購法", "85-1", "機關與廠商因履約爭議未能達成協議者，得向採購申訴審議委員會申請調解"),
    article("營造安全衛生設施標準", "19", "高度二公尺以上之開口部分，應設置護欄、護蓋或安全網"),
    Chunk("PCCES 03310", "spec_chapter", "施工綱要規範", "03310", "結構用混凝土", ""),
]

#: 假的語意空間：每個概念一個維度
CONCEPTS = [
    ("墜落", ["開口", "掉下去", "護欄"]),
    ("鄰房", ["鄰接", "隔壁"]),
    ("爭議", ["爭議", "糾紛"]),
    ("混凝土", ["混凝土", "灌漿"]),
]


def fake_vector(text: str) -> np.ndarray:
    vector = np.array([float(any(word in text for word in words)) for _, words in CONCEPTS] + [0.1])
    return (vector / np.linalg.norm(vector)).astype(np.float32)


@pytest.fixture
def index() -> InMemoryIndex:
    vectors = np.stack([fake_vector(chunk.text) for chunk in CHUNKS])
    return InMemoryIndex(CHUNKS, vectors, aliases={"採購法": "政府採購法"})


class TestChineseNumerals:
    @pytest.mark.parametrize(
        ("text", "value"), [("34", 34), ("三十", 30), ("十八", 18), ("二十二", 22), ("一百零一", 101), ("八十五", 85)]
    )
    def test_converts(self, text, value):
        assert cn_to_int(text) == value


class TestRefMatcher:
    @pytest.fixture
    def matcher(self) -> RefMatcher:
        return RefMatcher(CHUNKS, aliases={"採購法": "政府採購法"})

    def test_law_name_and_article_number(self, matcher):
        assert matcher.match("建築法第34條") == ["建築法 第 34 條"]

    def test_spaces_and_chinese_numerals(self, matcher):
        assert matcher.match("營造業法 第 三十 條 工地主任") == ["營造業法 第 30 條"]

    def test_longest_law_name_wins(self, matcher):
        assert matcher.match("營造業法施行細則第18條") == ["營造業法施行細則 第 18 條"]

    def test_alias(self, matcher):
        assert matcher.match("採購法第二十二條") == ["政府採購法 第 22 條"]

    def test_article_with_zhi(self, matcher):
        assert matcher.match("政府採購法第85條之1") == ["政府採購法 第 85-1 條"]

    def test_spec_chapter_code(self, matcher):
        assert matcher.match("規範 03310 章") == ["PCCES 03310"]

    def test_number_without_law_matches_every_law_with_that_article(self, matcher):
        assert matcher.match("第19條") == ["營造安全衛生設施標準 第 19 條"]

    def test_unknown_article_is_ignored(self, matcher):
        assert matcher.match("建築法第999條") == []


class TestFuse:
    def test_items_ranked_high_in_both_lists_win(self):
        ranked = fuse({"lexical": ["a", "b", "c"], "vector": ["b", "a", "d"]})
        assert [r.ref for r in ranked[:2]] in (["a", "b"], ["b", "a"])
        assert ranked[0].ranks.keys() == {"lexical", "vector"}

    def test_exact_matches_come_first_even_if_no_channel_found_them(self):
        ranked = fuse({"lexical": ["a", "b"]}, exact=["z"])
        assert ranked[0].ref == "z"
        assert ranked[0].ranks == {"exact": 1}

    def test_limit(self):
        assert len(fuse({"lexical": list("abcdefghijkl")}, limit=5)) == 5


class TestModes:
    def test_lexical_cannot_bridge_different_wording(self, index):
        refs = [r.ref for r in index.search("隔壁房子被弄歪", mode="lexical")]
        assert "建築法 第 69 條" not in refs[:1]

    def test_vector_finds_paraphrase(self, index):
        ranked = index.search("隔壁房子被弄歪", mode="vector", query_vector=fake_vector("隔壁房子被弄歪"))
        assert ranked[0].ref == "建築法 第 69 條"

    def test_hybrid_puts_named_article_first(self, index):
        query = "建築法第34條"
        ranked = index.search(query, mode="hybrid", query_vector=fake_vector(query))
        assert ranked[0].ref == "建築法 第 34 條"
        assert "exact" in ranked[0].ranks

    def test_hybrid_still_finds_paraphrase(self, index):
        query = "跟廠商有糾紛"
        ranked = index.search(query, mode="hybrid", query_vector=fake_vector(query))
        assert ranked[0].ref == "政府採購法 第 85-1 條"

    def test_vector_mode_needs_a_query_vector(self, index):
        with pytest.raises(ValueError):
            index.search("任何", mode="vector")


class TestCorpus:
    def test_articles_keep_chapter_heading_and_skip_headings_and_placeholders(self, tmp_path):
        laws = {
            "Laws": [
                {
                    "LawName": "測試法",
                    "LawArticles": [
                        {"ArticleType": "C", "ArticleNo": "", "ArticleContent": "   第 一 章 總則"},
                        {"ArticleType": "A", "ArticleNo": "第 1 條", "ArticleContent": "本法  用詞\r\n定義"},
                        {"ArticleType": "A", "ArticleNo": "第 1-1 條", "ArticleContent": "補充"},
                        {"ArticleType": "A", "ArticleNo": "第 2 條", "ArticleContent": "（刪除）"},
                        {"ArticleType": "A", "ArticleNo": "第 3 條", "ArticleContent": "〈移至建築構造編〉"},
                    ],
                }
            ]
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("ChLaw.json", json.dumps(laws, ensure_ascii=False).encode("utf-8-sig"))
        (tmp_path / "ChLaw.json.zip").write_bytes(buffer.getvalue())

        chunks = law_articles(tmp_path, ["測試法"])

        assert [c.ref for c in chunks] == ["測試法 第 1 條", "測試法 第 1-1 條"]
        assert chunks[0].heading == "第一章總則"
        assert chunks[0].content == "本法 用詞 定義"
        assert chunks[0].text.startswith("測試法 第 1 條（第一章總則）")

    def test_missing_law_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match="不存在的法"):
            law_articles(tmp_path, ["不存在的法"])

    def test_spec_chapters(self, tmp_path):
        path = tmp_path / "pcces.json"
        path.write_text(json.dumps({"chapters": [{"code": "03310", "name": "結構用混凝土"}]}), encoding="utf-8")

        [chunk] = spec_chapters(path)

        assert chunk.ref == "PCCES 03310"
        assert chunk.text == "施工綱要規範 03310（結構用混凝土）"
