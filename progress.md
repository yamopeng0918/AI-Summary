# AI Digest 專案進度

> 最後更新：2026-08-14
>
> 專案期程：2026-07-31～2026-08-27（四週，不含企畫日）
>
> 目前階段：GitHub Pages 與 Gemini 真實公開網頁來源驗收已完成；下一核心里程碑為正式分類模型
>
> 下次續作：建立人工標註分類資料集，訓練並可重現評估優於最大類基準的分類模型

## 專案目標

建立一套以個人使用為核心的 AI 摘要系統。使用者在本機提交公開網址，系統擷取內容、產生繁體中文摘要、預測既有分類並保存，再由 GitHub Pages 提供公開瀏覽、搜尋與篩選。

核心 MVP 的三種來源是：

- 公開且可直接讀取的一般網頁。
- YouTube 公開影片，包含無可用字幕的影片。
- 無須登入即可讀取的公開社群單篇貼文。

PDF／論文、圖片 OCR 與標籤篩選不屬於核心 MVP，只在核心範圍穩定且時程允許時加入。

## 目前整體進度

| 階段 | 狀態 | 進度摘要 |
|---|---|---|
| 企畫與需求收斂 | 已完成 | 核心三來源 MVP、非目標、架構邊界與驗收標準已納入核准規格 |
| 公開網頁本機里程碑 | 自動化驗證已完成 | URL 安全檢查、擷取、Gemini/OpenAI 摘要邊界與 provider 選擇、開發用分類器、Schema、原子 JSON 儲存、CLI 與 Astro 已串接；完整 Python suite 135 項通過 |
| 公開網頁真實來源驗收 | 已完成 | 使用者核准 `https://pala.tw/python-web-crawler/`；以預設 `gemini-3.6-flash` 完成擷取、摘要、分類、驗證與暫存 JSON 儲存 |
| 分類模型與評估 | 尚未開始 | 現有 `FixedClassifier` 僅供開發串接；正式模型必須嚴格優於最大類基準 |
| YouTube 公開影片 | 尚未開始 | 有字幕與無可用字幕都屬後續核心 MVP |
| 公開社群單篇貼文 | 尚未開始 | 不繞過登入、存取控制或私有內容限制 |
| GitHub repository 與 Pages | 已完成 | Pages Source 已設為 GitHub Actions；commit `b139f862553a65396c50eae5377cfbdddc86c4f2` 已由 workflow run `31767893009` 成功部署，公開首頁與新增摘要詳情頁均通過驗收 |
| PDF／論文、OCR、標籤篩選 | 選配／未開始 | 不列入核心 MVP |

## 已確認的產品與技術決策

- 主要使用者在本機新增、下架與重新發布內容；公開網站訪客只能瀏覽。
- 不建立網站後台、帳號系統、常駐後端或瀏覽器端 AI 請求。
- 每筆內容包含繁體中文短摘要、3～5 個重點、既有分類、1～5 個標籤、AI 編輯觀點與來源資料。
- 相同 `canonicalUrl` 預設拒絕重複新增；下架改為 `archived`，不刪除 JSON。
- Python CLI 負責處理管線；Astro 只讀取通過驗證且狀態為 `published` 的 JSON。
- 分類評估必須保存 Accuracy、Macro F1、混淆矩陣、標籤順序與最大類基準；測試 Accuracy 必須嚴格高於該基準才能宣稱完成。

## 第一里程碑驗收

- [x] 本地 HTML fixture 經真實 `WebExtractor`、確定性摘要替身、`FixedClassifier` 與 `SummaryRepository` 產生一筆合法 `published` JSON。
- [x] 相同 URL 第二次執行回報 `DUPLICATE_URL` 且不新增檔案。
- [x] Gemini 與 OpenAI 結構輸出驗證失敗時不會寫入不完整資料；CLI 預設 Gemini、可明確選擇 OpenAI，且只驗證所選 provider 的金鑰。
- [x] Astro 能驗證資料並建置首頁與獨立詳情頁，提供搜尋、分類篩選與日期排序。
- [x] 已執行追蹤檔案憑證格式掃描與差異空白檢查。
- [x] 使用一個由使用者提供並核准的真實公開文章與本機 `GEMINI_API_KEY` 完成端到端驗收；生成 JSON 已重新載入並通過 Schema 與敏感資訊檢查。

## 已知風險、阻礙與設定注意事項

| 項目 | 目前處理原則 |
|---|---|
| 公開來源受付費牆、登入或反爬蟲限制 | 不嘗試繞過，回報明確的結構化錯誤 |
| 真實網頁與 Gemini 驗收 | 已以核准文章與預設 `gemini-3.6-flash` 通過；SDK 仍輸出 Models API 的 AFC 建議警告，但不影響 structured-output 結果 |
| 開發用固定分類器 | 只用於管線串接，不視為分類模型完成 |
| Python CLI `PATH` | 目前 user-site Scripts 目錄未在 `PATH`；建議啟用 `.venv`，或明確加入對應 Scripts 目錄 |
| npm 安裝 script | `esbuild@0.28.2` 與 `esbuild@0.25.12` 仍有未核准安裝 script 通知；本里程碑未授權它們 |
| npm advisory audit | 後續可連線驗證已完成；`npm audit --json` 回報各嚴重度均為 0 漏洞 |
| GitHub Pages 遠端驗收 | Pages `build_type=workflow`；最新 run `31767893009` 成功部署 Unicode 路徑驗證修正與新摘要，並通過 workflow 內及獨立公開驗收 |
| YouTube 與社群平台變動 | 各來源保持獨立解析器，於對應里程碑以真實案例驗證 |
| 摘要或分類正確性 | 保留原文連結，分類器完成前不宣稱模型效能 |

## 進度紀錄

### 2026-08-14

- 新摘要 commit `32a12d1` 觸發 workflow run `31766478611`，Python 測試通過，但部署驗證器將 `git ls-files` 的中文 quoted path 當成實際檔名，於 `--tracked` 掃描失敗；Astro build 與 deploy 因此被跳過，既有公開站與本機摘要 JSON 均保持不變。
- 以 TDD 將 tracked-path 讀取改為 `git ls-files -z` binary output、NUL 分隔與 UTF-8 `surrogateescape` 解碼；新增中文檔名及 Git failure 回歸測試。完整 Python 135 項、Vitest 24 項、Astro 0 diagnostics、3 pages、combined tracked/dist verifier 與 `git diff --check` 均通過。
- 修正 commit `b139f86` 的 workflow run [`31767893009`](https://github.com/yamopeng0918/AI-Summary/actions/runs/31767893009) 結論為 `success`；cache-bypass 公開首頁包含 `20260814-python爬蟲新手筆記-pala-tw-8ed66e81` 與標題，中文詳情頁回傳 HTTP 200。
- 以 TDD 修正尾端斜線重新導向：canonical URL 仍為 `https://pala.tw/python-web-crawler`，HTTP transport 會保留伺服器 `Location` 提供的 `/`；回歸測試先重現 `TOO_MANY_REDIRECTS`，修正後完整 Python suite 133 項通過。
- Gemini API 對新使用者拒絕原預設 `gemini-2.5-flash`；依官方穩定模型文件與使用者核准，以 TDD 將預設更新為固定版本 `gemini-3.6-flash`，保留 `GEMINI_MODEL` override 且不加入自動 fallback。
- 使用核准文章 `https://pala.tw/python-web-crawler/` 執行預設 Gemini live acceptance，所有階段 `input`、`extract`、`summarize`、`classify`、`validate`、`save`、`complete` 均成功，record ID 為 `20260814-python爬蟲新手筆記-pala-tw-8ed66e81`。
- 暫存目錄僅產生一筆 JSON；以 `SummaryRepository` 重新載入後確認 Schema 有效、`published`、3 個重點、有效分類、5 個標籤，且不含 `GEMINI_API_KEY`、`OPENAI_API_KEY` 或 `GITHUB_TOKEN` 標記。暫存驗收資料未加入 repository。

### Task 5 local verification update (2026-08-14)

- Added `scripts/publish_url.py` as the thin one-command publishing entry point and covered it with `tests/test_publish_url_script.py`.
- Verified the new script locally with focused tests: `8 passed, 1 warning`.
- Re-ran the full Python suite after the final review fixes: `183 passed, 1 warning`, including the subprocess startup regression that executes `python -I scripts/publish_url.py --help` plus the new script-owned repository and non-200 workflow-status regressions.
- Kept Task 5 composition on the approved local defaults only: one shared `SummaryRepository(Path("data/summaries"))` for `cli.AddArticleWorkflow` creation and publisher resume, `cli._now()` timestamps, subprocess with `shell=False`, and urllib requests with the fixed `AI-Digest-Publisher/1.0` user agent.
- After the controller linked this worktree to the main checkout's existing matching frontend dependencies without network access, the remaining local frontend gates all passed: Vitest `24 passed`; Astro check reported `0 errors`, `0 warnings`, and `0 hints`; Pages build emitted `3 page(s) built`; the build:pages internal dist verifier passed; and `python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/` exited `0`.
- `git diff --check` exited `0` after the Task 5 documentation updates, with line-ending warnings only.
- End-to-end acceptance for the creation path is still pending a newly supplied or explicitly approved public article URL. No new live provider call, Git push, GitHub Actions run, or public Pages verification was executed in this Task 5 local pass.
- The first acceptance attempt for `https://henyahouse.com/python-learning-path/` stopped safely before saving because the CDN returned HTTP 403 to the extractor's sparse request headers. A controlled comparison confirmed the public page returns HTTP 200 when the existing project User-Agent includes a standard HTML `Accept` header; TDD added that content-negotiation header without browser impersonation or access-control bypass. The focused extractor suite passed `30` tests; live acceptance retry remains pending until this fix is committed and pushed.

### 2026-08-13

- 最終安全修正 `7f7dc1e` 已將生成的 `site/dist` 檔案納入 OpenAI key、GitHub token、私密金鑰與 `.env` 敏感資料掃描。
- GitHub Actions run [`31674616177`](https://github.com/yamopeng0918/AI-Summary/actions/runs/31674616177) 已成功部署 commit `7f7dc1ebd8fcb3e06ee79d748d5338f246aca0d1`。
- 重新執行公開 smoke checker，首頁與示範摘要詳情頁均通過；本機與 GitHub `master` 雜湊一致。

### 2026-08-10

- GitHub Pages Source 已設定為 GitHub Actions（`build_type=workflow`），公開網址為 <https://yamopeng0918.github.io/AI-Summary/>。
- 部署 commit `bf6f65b8953338c71b3e17d893089caca61d89fd` 的 workflow run [`31354210514`](https://github.com/yamopeng0918/AI-Summary/actions/runs/31354210514) 結論為 `success`；首頁與 `20260809-fictional-ai-digest-demo` 詳情頁均已發布。
- 獨立執行 `python scripts/smoke_pages.py --site-root https://yamopeng0918.github.io/AI-Summary/ --demo-id 20260809-fictional-ai-digest-demo --attempts 6 --delay-seconds 10 --timeout-seconds 15`，exit code 為 0。
- 首次 run `31352649651` 因 Python 3.12 annotation shadowing 失敗；以 TDD 修正為 `bf6f65b`，focused 1 項與完整 Python 113 項測試均通過。
- run `31354117164` 的 build 成功，但因 Pages 尚未建立而在 deploy 失敗；建立 Pages 並設為 workflow source 後，手動 dispatch 的 run `31354210514` 完整成功。
- `npm audit --json` 已成功取得 advisory 結果，info、low、moderate、high、critical 均為 0。

### 2026-08-09

- 完成 GitHub Pages base-path 支援、部署 artifact verifier、bounded public smoke checker 與 official Actions workflow；job-level Pages 權限維持最小範圍。
- 完整本機 gate 通過：Python 112 項、Vitest 24 項、Astro 0 diagnostics、2 個 routes，追蹤檔案與 `site/dist` 掃描均無違規。
- `site/dist` 的 internal links 已直接確認以 `/AI-Summary/` 開頭，外部原文連結使用 HTTPS。
- 本次 `npm audit --json` 因 registry endpoint 無法連線，狀態保持 **UNVERIFIED**；未重試或推測零漏洞。
- 尚未觸發真實 GitHub Pages deployment，也未對 <https://yamopeng0918.github.io/AI-Summary/> 執行公開 smoke acceptance，兩項均為 **UNVERIFIED**。
- 已將 GitHub repository 設為 `origin`，並把本機 `master` 推送至 `https://github.com/yamopeng0918/AI-Summary.git`；本機與遠端提交皆為 `3c644d3`。
- 根據核准規格將核心 MVP 統一為一般公開網頁、YouTube 公開影片與無須登入的公開社群單篇貼文。
- 將 PDF／論文、OCR 與標籤篩選移為核心 MVP 穩定後的選配工作。
- 完成公開網頁第一里程碑程式與本機 Astro 網站，並以本地 fixture-to-JSON 整合測試驗證真實擷取器邊界、Schema 儲存與重複 URL 拒絕。
- 文件明確記錄正式分類器的 Accuracy 必須嚴格優於最大類基準，`FixedClassifier` 僅為開發用。
- 未提供使用者核准的真實文章 URL 與 OpenAI 憑證，因此真實來源驗收保持 **UNVERIFIED**，未連線任意外部網站。

### 2026-07-30（歷史記錄）

- 完成產品需求訪談與範圍收斂。
- 完成專案企劃書：`AI_Digest_專案企劃書.docx`。
- 建立 `progress.md` 與 `todo.md` 作為後續專案管理文件。
- 完成企劃書與管理文件的日期、範圍及內容一致性檢查。
- 本次工作已收尾，尚未開始建立網站、摘要管線或 Codex Skill。
- 當時記錄的下一步為「開始前確認」與第 1 週的分類清單、資料模型；此交接點現已由 2026-08-09 的核准規格與實際可驗證成果取代。

## 下次工作交接

1. 建立 4～6 個互斥主分類的人工標註資料集與版本／內容雜湊。
2. 以固定 random seed 訓練 TF-IDF 與 Logistic Regression，記錄 Accuracy、Macro F1、混淆矩陣與最大類基準。
3. 模型測試 Accuracy 嚴格高於最大類基準後，再進入 YouTube 與公開社群里程碑。

## 更新規則

每次工作結束後，在「進度紀錄」最上方新增日期與完成事項，並同步更新整體階段、驗收勾選、`todo.md`、風險與重要決策。只能勾選已實際完成且通過相稱驗證的項目。

## Provider configuration update (2026-08-13)

- Provider-aware CLI composition is complete and automated tests cover the Gemini default, explicit OpenAI selection, invalid providers, selected-key validation, and key-free local commands.
- Gemini is the default (`GEMINI_API_KEY`, default model migrated to `gemini-3.6-flash` on 2026-08-14); OpenAI is selected explicitly (`OPENAI_API_KEY`, default model `gpt-5-mini`). There is no automatic fallback.
- Full Python automation passed: 133 tests. Gemini live acceptance completed on 2026-08-14 with the user-approved public article and a temporary repository.
