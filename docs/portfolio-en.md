# Engineering Regulation Compliance Platform — English Summary

**[Live demo](https://engineering-quality.vercel.app/)**: try the search and Q&A on 13 preset questions, including trap questions, with no login. The answers are real Claude Opus 5.5 outputs recorded during evaluation, and the page makes no API calls.

A platform for Taiwanese public-works quality engineers. It reads construction documents (contracts, specs, bills of quantities, scanned drawings), finds every regulation and standard they cite, checks each one against official government databases, and maps every work item to the spec chapters, contract clauses and drawings it depends on. All judgements carry an explanation and a human-review trail.

Stack: Python 3.12 / FastAPI / SQLAlchemy 2 (async) / PostgreSQL + pgvector, React + TypeScript, Claude API, sentence-transformers (bge-m3), PyMuPDF + Tesseract OCR. ~920 backend and ~140 frontend tests; CI boots the full Docker stack on PostgreSQL.

The three case studies below follow the same discipline: **measure a baseline first, keep a held-out set, report what didn't work.**

---

## 1. Regulation Q&A with verifiable citations ([details, Chinese](regulation-qa.md))

Users ask in plain language ("Do I need shoring if the trench is deeper than 1.5 m?"). Hybrid search retrieves 8 articles; Claude Opus 5.5 must answer **only from those articles** and quote them **verbatim**. A deterministic checker then verifies every quote is a literal substring of the article it cites (normalised for width and whitespace). Answers with no verified citation are not shown at all.

![A real answer: shoring is required beyond 1.5 m, with three verbatim citations each marked as verified](assets/regulation-qa.png)

![A trap question about fire-equipment inspection frequency: the model says the provided articles cannot answer it, instead of reusing the similar building-inspection article](assets/regulation-qa-refusal.png)

**Evaluation.** There are 54 answerable questions with labelled source articles. There are also 18 *unanswerable* trap questions whose answers live in laws outside the corpus. Most of these are deliberately close to it, for example asking about fire-equipment inspection frequency when the corpus only has building public-safety inspections. Every question is run with two retrievers (hybrid vs. the old lexical search), so the effect of retrieval on the final answer is isolated. An LLM judge grades correctness against the gold articles and flags any claim not supported by the cited text. The judge itself was spot-checked: all 14 sampled verdicts were agreed with. That spot check was done by the same model family, not an independent human, and this is stated as a limitation.

| Held-out test set | Hybrid retrieval | Lexical retrieval (old) |
|---|---:|---:|
| Correct | **75%** | 50% |
| Partially correct | 10% | 20% |
| **Wrong** | **0%** | **0%** |
| "Can't answer from these articles" (false refusal) | 15% | 30% |
| Trap questions correctly refused | **9/9** | 9/9 |
| Citations that pass verbatim verification | 92/92 | 86/86 |

Takeaways:
- **Retrieval sets the ceiling.** Same model and same prompt with only the retriever changed: accuracy moves by 25–35 points, tracking almost exactly whether the gold article was in the context.
- **When retrieval fails, the model refuses rather than inventing.** Zero wrong answers across all 54 answerable questions with hybrid retrieval.
- **The verifier never fired** (528/528 citations were verbatim), but it stays. It is the only safeguard that doesn't depend on model behaviour when the model, prompt or corpus changes.
- **Model choice: look at the kind of error, not just the accuracy.** Same questions, retrieval and judge, with only the model and effort changed (54 answerable + 18 trap questions):

  | Model / effort | Correct | Partial | Wrong | Traps refused | Cost / question | Median latency |
  |---|---:|---:|---:|---:|---:|---:|
  | Opus 5.5 / low | 83% | 7% | 0% | 18/18 | $0.026 | 6.0 s |
  | **Opus 5.5 / medium (adopted)** | **87%** | 6% | 0% | 18/18 | $0.028 | 6.8 s |
  | Opus 5.5 / high | 83% | 7% | 0% | 18/18 | $0.030 | 7.3 s |
  | Sonnet 5.5 / medium | 85% | 6% | 0% | 18/18 | $0.012 | 3.6 s |
  | Haiku 5.5 / medium | 70% | 20% | 0% | 18/18 | $0.0008 | 3.9 s |

  With 54 questions, one question is about 2 points, so the Opus effort levels and Sonnet are within noise on accuracy. Effort is not a useful lever here: more than half the cost is reading ~3.4k tokens of articles. Sonnet costs 42% as much at half the latency. However, one of its unsupported claims rewrote a mandatory "shall" (應, Government Procurement Act art. 85-4) as a discretionary "may" (得). That is a substantive legal error which reads perfectly naturally and which quote verification cannot catch, because the answer was altered, not the quote. Opus stays the default; Sonnet is a reasonable switch (`QA_MODEL`) for high-volume or "find the article, a human reads it" use. Haiku is 35× cheaper and still makes no wrong answers, but its partial answers rise from 6% to 20%, mostly from dropping list items.
- Two bugs were found by running real evaluations. One was a pre-existing structured-output schema bug that made the API reject nested objects. The other was a context-truncation bug found *on the test set*; both test sets were re-run after the fix and this is disclosed.

## 2. Hybrid semantic search with an honest evaluation ([details, Chinese](semantic-search.md))

Vectors live in the existing PostgreSQL via **pgvector** rather than a separate vector DB. The corpus is ~2.7k items and has to join against regulation status, so one database keeps one transaction, one backup and one permission model. Embeddings come from a local open model (bge-m3), so user documents never leave the server and results are reproducible.

87 labelled queries are split into a development set and a held-out test set written *after* the design was frozen.

| Method (bge-m3) | Dev Recall@5 | **Test Recall@5** |
|---|---:|---:|
| Bigram lexical (old search) | 0.51 | **0.54** |
| Pure vector | 0.80 | 0.80 |
| Exact-ID match + RRF(lexical, vector) — first design | 0.76 | 0.83 |
| **Exact-ID match + vector (adopted)** | 0.89 | **0.91** |

- **The evaluation overturned the first design.** The textbook three-way hybrid *lost* to pure vectors: equal-weight RRF let the weak lexical channel push correct semantic hits out of the top 5. Removing it gave 0.89.
- **The answer depends on the embedding model.** With a small model (MiniLM) the conclusion reverses: the lexical channel then patches the model's gaps.
- **pgvector gotchas found by checking parity with the offline evaluation:**
  - A secondary sort key disables the HNSW index.
  - `hnsw.ef_search` (default 40) silently caps results below the requested 50.
  - Without `ANALYZE` after a bulk rebuild, the planner picks approximate HNSW over an exact scan.

  After the fixes, PostgreSQL results match the evaluation 87/87.

## 3. Reading scanned contract drawings ([details, Chinese](case-study-scanned-drawings.md))

The contract drawings for a real project were stamped and then scanned: 286 pages with no text layer. Matching bill-of-quantities items to drawings needs each sheet's drawing number and title.

- **Drawing numbers read correctly: 35% → 92%.** The baseline also *misread* 6 of 12 structural pages. The target was "read more, misread nothing".
- **Techniques:**
  - OCR only the value cell, after erasing table lines with numpy.
  - Read each page several times at different resolutions and vote.
  - Use each volume's own drawing index as a whitelist.
  - Check numbering continuity, and fill gaps only when sequence numbers prove it.
- **Items flagged as "in the bill but not on any drawing": 312 → 30.** It stopped there on purpose. The remaining items genuinely need a human to look, and forcing more matches would hide exactly the items the feature exists to surface.

---

## What's not done

- **No independent human review yet.** The labels and judge verdicts in cases 1–2 haven't been checked by a domain expert.
- **Spec chapters have titles only**, no body text, so questions about spec content can only point to the chapter.
- **Retrieval doesn't yet pull in each law's enforcement rules alongside it.** This causes most "partially correct" answers.
