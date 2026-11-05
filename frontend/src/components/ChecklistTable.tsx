import type { CheckResult, ChecklistItem, DrawingSheet } from "../api/types";
import { CHECK_RESULT_LABELS, UNVERIFIED_LABEL, VERIFICATION_LABELS } from "../labels";

/** 篩選值：檢核結果，加上「全部」。 */
export type ChecklistResultFilter = CheckResult | "ALL";

const FILTER_OPTIONS: [ChecklistResultFilter, string][] = [
  ["ALL", "全部"],
  ["OK", CHECK_RESULT_LABELS.OK],
  ["SPEC_NOT_INCLUDED", CHECK_RESULT_LABELS.SPEC_NOT_INCLUDED],
  ["NEEDS_CONFIRMATION", CHECK_RESULT_LABELS.NEEDS_CONFIRMATION],
  ["BOQ_NOT_IN_DRAWINGS", CHECK_RESULT_LABELS.BOQ_NOT_IN_DRAWINGS],
  ["METHOD_UNDECIDED", CHECK_RESULT_LABELS.METHOD_UNDECIDED],
];

export function ChecklistSummary({
  ok,
  specNotIncluded,
  needsConfirmation,
  boqNotInDrawings = 0,
  methodUndecided = 0,
  hasDrawings = false,
  drawingsWithoutItems = [],
}: {
  ok: number;
  specNotIncluded: number;
  needsConfirmation: number;
  boqNotInDrawings?: number;
  methodUndecided?: number;
  hasDrawings?: boolean;
  drawingsWithoutItems?: DrawingSheet[];
}) {
  const cells: [CheckResult, number][] = [
    ["OK", ok],
    ["BOQ_NOT_IN_DRAWINGS", boqNotInDrawings],
    ["METHOD_UNDECIDED", methodUndecided],
    ["SPEC_NOT_INCLUDED", specNotIncluded],
    ["NEEDS_CONFIRMATION", needsConfirmation],
  ];

  // 依據只會掛在「OK」的列上（章對得到又抽到準則才是 OK），所以沒有 OK 就是一條依據也沒有。
  // 這裡只能說到「沒有任何工項列得出依據」，不能說「沒有任何工項對到規範書的章節」：
  // 後端 _result_for 在「章在規範書裡、但沒抽到相關準則」時也回「請確認依據」，
  // 那種情況下章是對到的。0／0／N 至少有三種來源——還沒建立檢核表（GET 只讀已建好的依據，
  // 後端的 test_get_before_any_build_builds_nothing 守住這個行為）、沒掛施工規範、
  // 規範書裡對得到的章都沒列相關準則——畫面上長得一樣，所以三種都列出來，不替使用者猜是哪一個。
  const nothingMatched = ok === 0 && specNotIncluded === 0 && needsConfirmation > 0;

  return (
    <>
      <div className="summary">
        {cells.map(([result, value]) => (
          <div key={result} className={`summary-cell summary-check-${result.toLowerCase()}`}>
            <span className="summary-value">{value}</span>
            <span className="summary-label">{CHECK_RESULT_LABELS[result]}</span>
          </div>
        ))}
      </div>

      {!hasDrawings && (
        <p className="hint">
          這個專案沒有掛契約圖，所以不判斷「標單有，契約圖沒有」，工項也不會列出相關圖號。
        </p>
      )}

      {boqNotInDrawings > 0 && (
        <p className="hint">
          「標單有，契約圖沒有」是契約圖的圖名裡找不到和這個工項相關的圖。系統只讀圖號與圖名，
          讀不懂圖面內容，請翻圖確認；施工測量、安全衛生這類一般要求（01 類章碼）本來就不畫在圖上，不列入。
        </p>
      )}

      {methodUndecided > 0 && (
        <p className="hint">
          「請檢討使用何種工法」是施工規範列出多種工法、契約文件沒有指定採用哪一種。系統不從圖面猜，
          請依相關圖號翻圖決定。
        </p>
      )}

      {drawingsWithoutItems.length > 0 && (
        <div className="hint">
          <strong>契約圖有、標單沒有</strong>：下列圖說的圖名對不到任何工項，可能是標單漏列，
          或只是圖名寫法不同，請人工確認。
          <ul>
            {drawingsWithoutItems.map((sheet) => (
              <li key={sheet.sheet_no}>
                {sheet.sheet_no} {sheet.title}（第 {sheet.page} 頁）
              </li>
            ))}
          </ul>
        </div>
      )}

      {/*
        「本案規範未收錄」不是缺漏清單，是要人工篩選的候選：這一類裡有一大塊是行政性章節
        （計量與計價之類），施工規範書本來就不會收，把整批當成缺陷會讓人白擔心一場。
        所以這句話要貼在數字旁邊，而不是藏在說明文件裡。
      */}
      {specNotIncluded > 0 && (
        <p className="hint">
          「本案規範未收錄」是工項的章碼在全國共通的施工綱要規範裡有、本案施工規範書卻沒有。
          這需要人工篩選，不是整批都是缺漏：施工規範書不收錄行政性章節（例如 01271
          計量與計價）是合理的。章節欄會列出缺的是哪一章，可以依章碼分流。
        </p>
      )}

      {needsConfirmation > 0 && !nothingMatched && (
        <p className="hint">
          「請確認依據」是系統沒辦法替這個工項找到依據：沒有計價代碼、代碼不屬於施工綱要規範，
          或本案規範書那一章沒有抽到相關準則。
        </p>
      )}

      {nothingMatched && (
        <p className="hint">
          目前沒有任何工項列得出依據。可能是還沒建立檢核表、這個專案沒有掛上施工規範，
          或掛上的規範書裡對得到的章節都沒有列出相關準則。
        </p>
      )}

      {/*
        標籤與其說明放在同一個元件：看到「未查證」的人，旁邊就有解釋它不代表那條依據不存在。
        說明刻意不用「查無此法規」這個詞——整個畫面上不該出現那五個字，連否定句裡也不要，
        這樣「畫面上沒有任何地方說查無」才是一句能直接用文字搜尋驗證的話。
      */}
      {ok > 0 && (
        <p className="hint">
          依據欄標示「{UNVERIFIED_LABEL}」的，是系統沒有查證那一條，不代表這個法規或標準不存在：
          標準（CNS、ASTM、ISO、JIS）只有在啟用標準目錄時才查，法規則是在全國法規索引裡找不到完全同名
          的名稱。有標示現行有效等狀態的，才是查到的。
        </p>
      )}
    </>
  );
}

/**
 * 查證狀態標示。null 是「沒查」，不是「查過、不存在」。
 *
 * 判斷用 `== null`，連 undefined 一起接住：舊版後端的回應根本沒有這個欄位（例如沒帶
 * --reload 的 uvicorn 還在跑舊程式），值是 undefined 而不是 null。用 `=== null` 的話
 * 它會掉進下面的 `status.toLowerCase()` 丟出例外，而這個畫面沒有 error boundary，
 * 整棵樹都會消失。沒有欄位也是「沒查」。
 */
function VerificationTag({ status }: { status: string | null | undefined }) {
  if (status == null) {
    // 絕大多數依據都是未查證，用淡色字而不是標籤，才不會蓋過少數真正查到的狀態
    return <span className="unverified">{UNVERIFIED_LABEL}</span>;
  }
  // 不認得的狀態值照原樣顯示：它確實是查過的結果，說成「未查證」或「查無」都不對
  const label = VERIFICATION_LABELS[status] ?? status;
  return <span className={`badge badge-${status.toLowerCase()}`}>{label}</span>;
}

/** 契約圖與工法：相關圖號給人去翻，工法只填契約文件明寫的那一種。 */
function DrawingMethodCell({ item }: { item: ChecklistItem }) {
  // 舊版後端的回應沒有 drawings / method，當作沒有
  const drawings = item.drawings ?? [];
  if (drawings.length === 0 && !item.method) return <>—</>;
  return (
    <>
      {drawings.length > 0 && (
        <div>
          圖號：
          {drawings.map((sheet) => (
            <span key={sheet.sheet_no} className="chapter-code" title={`${sheet.title}（第 ${sheet.page} 頁）`}>
              {sheet.sheet_no}{" "}
            </span>
          ))}
          {drawings.some((sheet) => sheet.is_ocr) && (
            <span className="unverified" title="圖號圖名由 OCR 從掃描的標題欄讀出，可能有錯字">（OCR）</span>
          )}
        </div>
      )}
      {item.method && (
        <div title={item.method.evidence ?? undefined}>
          工法：
          {item.method.selected ? (
            <strong>{item.method.selected}</strong>
          ) : (
            <span className="unverified">未指定（{item.method.options.join("／")}）</span>
          )}
        </div>
      )}
    </>
  );
}

/** 每一章可下載的橘框表單初稿：（路徑, 連結文字） */
const DRAFT_FORMS: [string, string][] = [
  ["export", "標準表初稿"],
  ["self-inspection/export", "自主檢查表初稿"],
  ["supervision/export", "監造抽查標準表初稿"],
  ["method-statement/export", "施工要領初稿"],
];

/** 機電章（11 設備、13 消防、14 輸送、15 機械、16 電機）才有設備功能運轉檢測 */
function isEquipmentChapter(code: string): boolean {
  return ["11", "13", "14", "15", "16"].includes(code.slice(0, 2));
}

/** 契約欄：契約書提到這個工項（或它所屬分項）的地方。條號讀不到，只給頁碼與前面最近的標題。 */
function ContractCell({ item }: { item: ChecklistItem }) {
  const refs = item.contract_refs ?? [];
  if (refs.length === 0) return <>—</>;
  return (
    <ul className="bases">
      {refs.map((ref, index) => (
        <li key={`${index}-${ref.page}`} title={`「${ref.excerpt}」（以「${ref.keyword}」找到）`}>
          {ref.page !== null && <span className="chapter-code">p{ref.page}</span>} {ref.heading ?? ""}
        </li>
      ))}
    </ul>
  );
}

function ChapterCell({ item, projectId, demo }: { item: ChecklistItem; projectId?: string; demo?: boolean }) {
  const query = demo ? "?demo=true" : "";
  if (item.chapter) {
    return (
      <>
        <span className="chapter-code">{item.chapter.code}</span> {item.chapter.title}
        {projectId && (
          <div className="draft-forms">
            {/* 橘框表單：從本案規範這一章擷取的初稿，要品管／監造人員補正。三張表出自同一份初稿 */}
            {DRAFT_FORMS.map(([path, label]) => (
              <a key={label} href={`/api/projects/${projectId}/quality-standards/${item.chapter!.code}/${path}${query}`}>
                {label}
              </a>
            ))}
            {isEquipmentChapter(item.chapter.code) && (
              <a href={`/api/projects/${projectId}/quality-standards/${item.chapter.code}/function-test/export${query}`}>
                功能運轉檢測初稿
              </a>
            )}
          </div>
        )}
      </>
    );
  }
  // chapter 是 null 時仍然有章碼：「本案規範未收錄」的列就靠它指出缺的是哪一章。
  // 這裡不補「規範書沒有這章」之類的話——沒建過檢核表時每一列的 chapter 都是 null，
  // 那句話對那些列不成立。
  if (item.chapter_code) {
    return <span className="chapter-code">{item.chapter_code}</span>;
  }
  return <>—</>;
}

export function ChecklistTable({
  items,
  resultFilter,
  onResultFilterChange,
  projectId,
  demo,
}: {
  items: ChecklistItem[];
  resultFilter: ChecklistResultFilter;
  onResultFilterChange: (value: ChecklistResultFilter) => void;
  /** 有給才顯示「標準表初稿」下載連結 */
  projectId?: string;
  /** 下載連結加上 ?demo=true：初稿的「（待填）」用示範內容補齊 */
  demo?: boolean;
}) {
  if (items.length === 0) {
    return (
      <p className="hint">
        這個專案還沒有可檢核的工項。先把標單掛上去並建立工項，再把施工規範掛上去，按「建立檢核表」。
      </p>
    );
  }

  const rows = resultFilter === "ALL" ? items : items.filter((item) => item.result === resultFilter);

  return (
    <>
      <div className="filters">
        <div>
          <label htmlFor="checklist-result-filter">檢核結果</label>
          <select
            id="checklist-result-filter"
            value={resultFilter}
            onChange={(event) => onResultFilterChange(event.target.value as ChecklistResultFilter)}
          >
            {FILTER_OPTIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <span className="hint">
          顯示 {rows.length} 筆，共 {items.length} 筆
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="hint">沒有符合這個檢核結果的工項。</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>項次</th>
              <th>工程項目</th>
              <th>檢核結果</th>
              <th>章節</th>
              <th>契約</th>
              <th>契約圖／工法</th>
              <th className="col-bases">依據</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <tr
                key={item.work_item_id}
                className={item.result !== "OK" && item.result !== "NEEDS_CONFIRMATION" ? "attention" : ""}
              >
                <td className="nowrap">{item.item_no}</td>
                <td>{item.name}</td>
                <td>
                  <span className={`badge badge-check-${item.result.toLowerCase()}`}>
                    {CHECK_RESULT_LABELS[item.result] ?? item.result}
                  </span>
                  {/* 同時成立的其他問題（舊版後端沒有 issues 欄位，所以用 ?.） */}
                  {item.issues?.slice(1).map((issue) => (
                    <div key={issue} className="hint">另：{CHECK_RESULT_LABELS[issue] ?? issue}</div>
                  ))}
                </td>
                <td>
                  <ChapterCell item={item} projectId={projectId} demo={demo} />
                </td>
                <td>
                  <ContractCell item={item} />
                </td>
                <td>
                  <DrawingMethodCell item={item} />
                </td>
                <td className="col-bases">
                  {item.bases.length === 0 ? (
                    "—"
                  ) : (
                    <ul className="bases">
                      {item.bases.map((basis, index) => (
                        // 同一章可能引同一個名稱兩次，名稱本身不能當 key
                        <li key={`${index}-${basis.reference}`} title={basis.detail ?? undefined}>
                          <span className="basis-name">{basis.reference}</span>
                          <VerificationTag status={basis.verification_status} />
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
