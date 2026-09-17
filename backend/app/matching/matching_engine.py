"""比對引擎：決定一筆引用對應到哪一部法規、信心多少、狀態是什麼。

設計原則（docs/architecture.md 1.5、第 5 節）：
- 規則優先：別名完全命中 > 標準編號命中 > 字串相似度。
- LLM 只在相似度落在「不上不下」的區間時才被詢問，而且只會補充比對理由，
  不會覆蓋規則引擎算出來的結果，也不會直接決定法規狀態。
- 整層可以透過 ENABLE_LLM_FALLBACK 關掉，關掉後系統照樣完整運作。

狀態判定規則：
    信心 >= MATCH_AUTO_THRESHOLD     -> 採用該法規的官方狀態
    信心 >= MATCH_POSSIBLE_THRESHOLD -> 採用該法規的官方狀態，但標記為「疑似」
    信心 <  MATCH_POSSIBLE_THRESHOLD -> NOT_FOUND
    來源無法確認最新版（付費標準）    -> POSSIBLE_MATCH（不論信心多高）
"""

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from app.ai.base import LLMCallRecord, LLMProvider
from app.core.config import settings
from app.core.enums import RegulationStatus, RegulationType
from app.matching.normalizer import clean_text

# 各種命中方式的基礎分數
SCORE_EXACT_NAME = 1.0
SCORE_STANDARD_NUMBER = 0.97
SCORE_ALIAS = 0.95


@dataclass(slots=True)
class MatchCandidate:
    """比對用的統一格式。資料庫裡的法規與外部來源的搜尋結果都會轉成這個。"""

    key: str
    name: str
    normalized_name: str
    type: str
    status: str
    aliases: list[str] = field(default_factory=list)
    standard_number: str | None = None
    can_confirm_currency: bool = True


@dataclass(slots=True)
class MatchDecision:
    candidate: MatchCandidate | None
    confidence: float
    status: RegulationStatus
    reasons: list[str]
    ai_record: LLMCallRecord | None = None

    @property
    def is_tentative(self) -> bool:
        """信心不足以自動採信，前端會顯示「疑似」。"""
        return 0 < self.confidence < settings.MATCH_AUTO_THRESHOLD


class MatchingEngine:
    def __init__(self, llm_provider: LLMProvider | None = None):
        self._llm = llm_provider

    async def match(
        self,
        normalized_name: str,
        candidates: list[MatchCandidate],
        standard_number: str | None = None,
        context: str = "",
    ) -> MatchDecision:
        if not candidates:
            return MatchDecision(
                candidate=None,
                confidence=0.0,
                status=RegulationStatus.NOT_FOUND,
                reasons=["所有已啟用的法規來源都查不到這個名稱"],
            )

        candidates, blocked_reason = self._eligible_candidates(candidates, standard_number)
        if blocked_reason is not None:
            return MatchDecision(
                candidate=None,
                confidence=0.0,
                status=RegulationStatus.NOT_FOUND,
                reasons=[blocked_reason],
            )

        best, score, reasons = self._best_candidate(normalized_name, candidates, standard_number)

        ai_record = None
        if (
            self._llm is not None
            and self._llm.enabled
            and settings.MATCH_POSSIBLE_THRESHOLD <= score < settings.MATCH_AUTO_THRESHOLD
        ):
            score, extra_reasons, ai_record = await self._ask_llm(
                normalized_name, best, context, score
            )
            reasons.extend(extra_reasons)

        status = self._decide_status(best, score, reasons)
        return MatchDecision(
            candidate=best if status is not RegulationStatus.NOT_FOUND else None,
            confidence=round(score, 4),
            status=status,
            reasons=reasons,
            ai_record=ai_record,
        )

    # --- 內部 ---

    def _eligible_candidates(
        self, candidates: list[MatchCandidate], standard_number: str | None
    ) -> tuple[list[MatchCandidate], str | None]:
        """文件裡出現標準編號時，只有標準型別的候選有資格參賽。

        理由是實測出來的：工程規範的章節名稱是工項/材料名（「卜特蘭水泥」、「鋼筋」、
        「品質管理」），和帶編號的標準引用在字面上幾乎一樣，相似度會衝到 0.90 以上而
        被自動採信。把一份 CNS 標準判成一個施工綱要規範章節，是「有信心的錯」——
        比誠實回答查不到傷害大得多。

        刻意只在「引用本身帶標準編號」這個高精確度訊號上設限。抽取器猜的
        regulation_type 會錯，拿它做通用的型別相容性檢查會製造大量假 NOT_FOUND。
        """
        if not standard_number:
            return candidates, None

        eligible = [c for c in candidates if c.type == RegulationType.STANDARD]
        if eligible:
            return eligible, None
        return candidates, (
            f"引用帶標準編號（{standard_number}），但候選中沒有標準型別的資料。"
            "名稱相近的法規或工程規範不予採用，需人工查證"
        )

    def _best_candidate(
        self, name: str, candidates: list[MatchCandidate], standard_number: str | None
    ) -> tuple[MatchCandidate, float, list[str]]:
        target = clean_text(name).casefold()
        scored: list[tuple[float, str, MatchCandidate]] = []

        for candidate in candidates:
            candidate_name = clean_text(candidate.normalized_name or candidate.name).casefold()

            if target == candidate_name:
                scored.append((SCORE_EXACT_NAME, "名稱完全相同", candidate))
                continue

            if (
                standard_number
                and candidate.standard_number
                and clean_text(standard_number).casefold()
                == clean_text(candidate.standard_number).casefold()
            ):
                scored.append(
                    (SCORE_STANDARD_NUMBER, f"標準編號相同（{candidate.standard_number}）", candidate)
                )
                continue

            alias_hit = next(
                (a for a in candidate.aliases if clean_text(a).casefold() == target), None
            )
            if alias_hit:
                scored.append((SCORE_ALIAS, f"命中別名「{alias_hit}」", candidate))
                continue

            # 名稱本身與所有別名取最高相似度
            texts = [candidate_name] + [clean_text(a).casefold() for a in candidate.aliases]
            ratio = max(fuzz.token_set_ratio(target, text) for text in texts) / 100.0
            scored.append((ratio, f"名稱相似度 {ratio:.0%}", candidate))

        scored.sort(key=lambda item: -item[0])
        score, reason, best = scored[0]
        return best, score, [reason, f"比對對象：{best.name}（來源狀態 {best.status}）"]

    async def _ask_llm(
        self, name: str, candidate: MatchCandidate, context: str, score: float
    ) -> tuple[float, list[str], LLMCallRecord | None]:
        """相似度落在模糊區間時詢問 LLM。只微調分數與補充理由，不決定狀態。"""
        result = await self._llm.judge_similarity(name, candidate.name, context)
        if not result.ok:
            return score, ["（LLM 輔助判斷未取得結果，維持規則引擎的分數）"], result.record

        judgement = result.value
        reasons = [
            f"LLM 輔助判斷：{'相同' if judgement.is_same else '不同'}"
            f"（信心 {judgement.confidence:.0%}）— {judgement.reason}"
        ]
        # 最多只讓 LLM 把分數推到自動門檻邊緣，主導權仍在規則引擎
        if judgement.is_same:
            adjusted = min(settings.MATCH_AUTO_THRESHOLD, score + 0.1 * judgement.confidence)
        else:
            adjusted = max(0.0, score - 0.1 * judgement.confidence)
        return adjusted, reasons, result.record

    def _decide_status(
        self, candidate: MatchCandidate, score: float, reasons: list[str]
    ) -> RegulationStatus:
        if score < settings.MATCH_POSSIBLE_THRESHOLD:
            reasons.append(
                f"信心 {score:.0%} 低於門檻 {settings.MATCH_POSSIBLE_THRESHOLD:.0%}，判定為查無此法規"
            )
            return RegulationStatus.NOT_FOUND

        if not candidate.can_confirm_currency:
            reasons.append(
                "資料來源只能確認此標準存在，無法確認是否為最新版本（付費標準常見情形），"
                "需人工查證"
            )
            return RegulationStatus.POSSIBLE_MATCH

        try:
            source_status = RegulationStatus(candidate.status)
        except ValueError:
            reasons.append(f"來源回傳了無法辨識的狀態「{candidate.status}」")
            return RegulationStatus.UNKNOWN

        if score >= settings.MATCH_AUTO_THRESHOLD:
            return source_status

        reasons.append(
            f"信心 {score:.0%} 未達自動採信門檻 {settings.MATCH_AUTO_THRESHOLD:.0%}"
        )
        # 信心不足時，「現行有效」是唯一會讓人安心的狀態，也因此是唯一會誤導人的狀態。
        # 既然還不確定比對到的是不是同一部法規，就不能給這個肯定的答案，
        # 一律降級為需人工確認（docs/database.md 第 4 節：不要給看似肯定但可能誤導的判斷）。
        # AMENDED / REPEALED 本來就是「要注意」，保留原狀態並標示疑似即可。
        if source_status is RegulationStatus.ACTIVE:
            reasons.append(
                f"比對到的是名稱不同的「{candidate.name}」，"
                "在確認是同一部法規之前不宣告為現行有效，請人工確認"
            )
            return RegulationStatus.POSSIBLE_MATCH

        reasons.append("狀態標記為疑似，建議人工確認")
        return source_status
