# AI Digest 待辦清單

> 專案期程：2026-07-31～2026-08-27
>
> 最後同步：2026-09-03
>
> 狀態標記：`[ ]` 尚未開始或尚未通過驗證、`[x]` 已完成且有驗證證據
>
> 核心 MVP：一般公開網頁、YouTube 公開影片、無須登入的公開社群單篇貼文

## 企畫階段

- [x] 完成產品需求訪談與範圍收斂。
- [x] 完成原始專案企劃書、`progress.md` 與 `todo.md`。
- [x] 將後續核准的三來源 MVP、架構邊界、安全規則與驗收標準寫入設計規格。
- [x] 將 PDF／論文、OCR 與標籤篩選移到選配範圍。

## 第一里程碑：公開網頁本機流程

### 資料與儲存

- [x] 定義摘要 Schema、必填欄位、別名與時區規則。
- [x] 定義三種核心來源類型：`web`、`youtube`、`social`。
- [x] 定義 1～5 個標籤的清理與去重規則。
- [x] 定義 `published`／`archived` 狀態與含時區時間。
- [x] 定義 `canonicalUrl` 正規化與重複 URL 拒絕。
- [x] 建立 Schema 驗證後才原子寫入的獨立 JSON 儲存層。
- [x] 建立統一 `stage`、`code`、`message`、`retryable` 錯誤結構。

### 公開網頁擷取與摘要

- [x] 驗證只允許公開 HTTP(S) 目的地，並防止私有位址與重定向繞過。
- [x] 擷取公開 HTML 文章的標題、作者、日期、正文與正規化來源 URL。
- [x] 排除導覽與非正文內容。
- [x] 對登入、付費牆、無足夠正文、HTTP 與網路失敗回報明確錯誤。
- [x] 建立 Gemini 與 OpenAI 結構化摘要邊界，驗證短摘要、3～5 個重點、1～5 個標籤與編輯觀點。
- [x] 確認摘要回傳不合格時不會寫入不完整資料。

### 管線與 CLI

- [x] 串接 URL 正規化、重複預檢、擷取、摘要、開發用分類與儲存。
- [x] 實作 `add`、`list`、`show`、`archive` 與 `publish` CLI 指令。
- [x] 以本地 HTML fixture、真實 `WebExtractor`、確定性摘要替身、`FixedClassifier` 與暫存 repository 完成 fixture-to-JSON 整合測試。
- [x] 驗證同一 URL 第二次新增被拒絕且檔案數不變。
- [x] 取得使用者核准的公開文章 URL 與本機 `GEMINI_API_KEY`，以預設 `gemini-3.6-flash` 完成一次 Gemini 真實來源驗收與暫存 JSON 驗證。

### Astro 本機網站

- [x] 建立已發布摘要卡片列表與獨立詳情頁。
- [x] 顯示短摘要、重點、分類、標籤、AI 編輯觀點、來源與原文連結。
- [x] 支援關鍵字搜尋、單一分類篩選與最新／最舊日期排序。
- [x] 忽略 `archived` 資料、處理無資料與無搜尋結果；資料驗證失敗時採 fail-closed，直接中止靜態建置。
- [x] 完成手機與桌面版基本響應式介面與本機靜態建置。
- [x] 建立 GitHub Pages workflow、`/AI-Summary/` base path、artifact verifier 與本機 `build:pages` gate。
- [x] 觸發真實 GitHub Pages deployment，並對公開首頁與 demo 詳情頁完成 smoke acceptance（最新 run `31674616177`，commit `7f7dc1ebd8fcb3e06ee79d748d5338f246aca0d1`）。
- [x] 為每筆已發布摘要產生 OG PNG，使用官方完整 Pan-CJK Regular／Bold OTF、渲染前 fail-closed cmap 檢查與 `18`／`40`／`36` 安全排版；詳情頁 metadata、首頁卡片、分類右上／來源 footer、containment-first 圖片 resolver 與 `--dist` 全樹 inventory、記憶體有界 PNG decoder、完整 artifact gate，以及全部六張原始解析度視覺驗收均通過。

### 文件與安全收尾

- [x] 撰寫 Windows PowerShell 的 Python、CLI、測試、Astro 開發與靜態建置說明。
- [x] 記錄 `FixedClassifier` 僅供開發使用。
- [x] 記錄 user-site CLI `PATH` 注意事項與尚未核准的 esbuild 安裝 script 通知。
- [x] 執行 Python 與前端測試、Astro 正式建置、憑證格式掃描與 `git diff --check`。

## 後續核心 MVP

### 正式分類模型

- [x] 完成審核批次一的 60 個公開來源候選（六類各 10 筆），逐頁確認可直接讀取並全部維持 `pending`。
- [x] 建立分類資料審核指南與離線列數／狀態／分類計數命令。
- [x] Batch 1: applied explicit user approval to 60 rows (ten per category); no rejected or replacement rows.
- [x] Batch 2: applied explicit user approval to 60 rows (ten per category); no rejected or replacement rows.
- [x] Batch 3: researched and individually opened 60 directly readable public-source candidates (ten per category); all approved after explicit user review.
- [x] Batch 3: complete row-by-row review and apply only explicit approval, rejection, or replacement decisions.
- [x] 建立 4～6 個互斥主分類的人工標註資料集與版本／內容雜湊。
- [x] 以固定 random seed 訓練 TF-IDF 與 Logistic Regression 分類器。
- [x] 儲存訓練／測試筆數、各類樣本數、Accuracy、Macro F1、混淆矩陣與標籤順序。
- [x] 計算最大類基準 Accuracy，並驗證測試 Accuracy **嚴格高於**該基準後才標記分類模型完成。
- [x] 將正式分類器、180 筆已審核資料與可重現 artifacts 合併至 `master`，完成合併後 gates 並推送 GitHub（merge commit `f9977de`）。

### YouTube 公開影片

- [x] 建立獨立 YouTube 來源解析器與公開影片存取驗證。
- [x] 支援有可用字幕的公開影片。
- [x] 支援無可用字幕影片的影音處理與轉錄流程。
- [x] 處理驗證失效、限流、工具變動與中斷後可重試狀態。
- [x] 有字幕與無可用字幕各以一個使用者核准的真實公開案例驗收（2026-08-26 兩案均 exit 0 並到達 `complete`，資料驗證及本機／遠端零殘留檢查通過）。

#### Provider-aligned 音訊轉錄（2026-08-22）

- [x] 新增 Gemini Files API 音訊轉錄器，並驗證成功時依序轉錄及刪除遠端檔案。
- [x] 驗證畸形回應、SDK／HTTP／本機錯誤、清理失敗、雙重失敗與程序中斷均使用安全錯誤及確定性清理。
- [x] 讓 `AI_DIGEST_PROVIDER` 同時選擇摘要器與無字幕轉錄器，且 Gemini／OpenAI 各只使用自己的金鑰與模型設定，不自動 fallback。
- [x] 以本地 fake 與 fixture 完成 Task 1～3 相關驗證：transcriber 專項 `39 passed`；CLI、YouTube、media 與 transcriber 集合 `177 passed`。
- [x] 更新 `.env.example`、README 與舊 YouTube 設計的 supersession note，並完成 provider-aligned 完整 Python／前端／正式建置／部署安全 gates（Python `444 passed`、Vitest `25 passed`、Astro 0 diagnostics／5 pages、Schema/storage `28 passed`）。
- [x] 核准 Gemini Files 清理有限重試設計：只重試 delete，最多三次，等待 1／2 秒；404 視為成功，暫時性錯誤才重試，且保留主要錯誤優先與安全輸出。
- [x] 完成 Gemini Files 清理有限重試的嚴格 TDD 實作計畫與完整驗收步驟。
- [x] 完成 Gemini Files 清理有限重試實作並通過完整自動化 gates（Python `453 passed, 2 warnings`；Schema/storage `28 passed, 1 warning`；Vitest `25 passed`；Astro 0 diagnostics／5 pages；deployment verifier、diff 與 `site/dist` 媒體掃描通過）。
- [x] 補齊 Gemini Files cleanup-retry final review 的自動化證據：focused `tests/test_gemini_transcriber.py` 為 `32 passed, 2 warnings`，驗證 first-success、HTTP 400、unexpected exception 與 cleanup interrupt 均不會不必要地 retry 或 sleep，並維持安全輸出。
- [x] 以核准的無字幕影片完成隔離真實驗收並驗證無本機／遠端暫存資訊殘留（2026-08-26 明確核准的付費重試 exit 0，完整到達 `complete`；唯一 JSON 通過 Schema、來源、內容、時區與禁止標記檢查，媒體與 Gemini Files 均為 0，精確隔離 root 已移除）。

### 公開社群單篇貼文

- [x] 定義核心 MVP 的 Bluesky 公開單篇貼文平台與獨立解析器。
- [x] 擷取無須登入即可讀取的 Bluesky 公開單篇貼文文字、作者、日期與 DID canonical 原始連結。
- [x] 對私人內容、登入限制、付費內容、回覆或非單篇貼文明確失敗且不繞過限制。
- [x] 完成 Bluesky 本機 CLI、Schema／儲存與 Astro 搜尋／排序／OG 社群標籤的回歸驗證（Python `601 passed, 2 skipped, 1 warning`；Vitest `52 passed`；兩種 Astro build 均 0 diagnostics／7 pages）。
- [x] 使用者核准真實驗收後，以 Bluesky 官方帳號穩定公開、非回覆貼文執行一次 AppView 擷取驗收。
- [x] 依明確授權對核准 Bluesky 貼文執行一次付費摘要，並驗證 DID canonical URL、`sourceType: social` 與保存 JSON。
- [x] 依明確授權提交 Bluesky 摘要與驗收記錄，並 push 至 `origin/master`（commit `5189f96`）。
- [x] 監看 Pages workflow run `33171319697` 成功，並驗證公開列表／搜尋資料、詳情、來源連結與 `1200×630` OG image。
- [x] 以使用者核准的真實公開單篇 Bluesky 貼文完成端到端驗收。

### 內容管理與部署

- [x] 完成 Windows 互動式終端 UTF-8 相容性根因診斷與設計核准。
- [x] 依核准規格以 TDD 修正 Windows CP950 下 `list`／`show` 的 Unicode 輸出，並完成完整 Python 與安全驗證（實作 `d8ed9ae`、CP950 regression 補強 `13ad440`；Python `608 passed, 2 skipped, 1 warning`；tracked verifier 與 `git diff --check` exit `0`）。
- [x] 支援本機編輯與重新產生摘要：`edit`／`regenerate` CLI、Schema 驗證後原子覆寫與失敗保留均已完成；第二輪 final review 修正 `75785f1` 後，focused Python `94 passed, 1 warning`、完整 Python `670 passed, 2 skipped, 1 warning`、7 筆保存資料重驗證、tracked verifier、diff check 與無金鑰隔離 edit smoke 均有證據。未執行真實付費重新產生、push 或部署。
- [x] 支援下架與重新發布，並保留建立與更新時間。
- [x] 實作 `evaluate-classifier` 指令。
- [x] 完成本機 `build-site` CLI 與文件，並於 2026-09-02 fast-forward 整合至本機 `master`；實作、審查與合併後驗證證據記錄於 `progress.md`。
- [x] 完成 `deploy` CLI 獨立設計、TDD 實作與 final-review 修正（2026-09-02～03：`602e4e1`、`58730e3`、`fbaa000`、`568d9bc`、`bf2fd9b`、`492c80a`、`b492ce5`）；`deploy` 僅輸出結構化 JSON Lines，所有子程序輸出均捕捉，獨立 `build-site` 仍保留即時診斷。final-review focused Python 為 `103 passed, 1 warning`，完整 Python 為 `715 passed, 2 skipped, 1 warning`；先前 Vitest `67 passed`、`build-site`、tracked／dist verifier 與 diff check 證據仍保留。
- [ ] 在使用者明確授權後執行一次真實 `ai-digest deploy`，驗證 push（如需要）、相同 HEAD 的 GitHub Pages workflow 與公開 smoke acceptance；完成前不得標記 deploy 完成。
- [x] 在取得明確授權後設定 GitHub repository，並推送 `master`。
- [x] 建立 official GitHub Pages workflow，並完成本機 build、測試、base-path 連結與敏感資料 gate。
- [x] 完成真實 GitHub Pages deployment 與公開 smoke acceptance（<https://yamopeng0918.github.io/AI-Summary/>）。
- [x] 執行部署前建置與追蹤檔案、`site/dist` 敏感資料掃描。
- [x] 驗證部署失敗時保留本機資料與既有公開站；修正 Unicode 路徑 gate 後由 workflow run `31767893009` 成功重試部署。

## 選配後續工作（不列入核心 MVP）

- [ ] 文字型 PDF／論文擷取與摘要。
- [ ] 掃描型 PDF 與圖片 OCR。
- [ ] 標籤篩選。
- [ ] 付費牆或需登入來源（不得繞過存取控制）。
- [ ] 私人社群內容或完整討論串。
- [ ] 網站管理後台與多使用者帳號。

## 歷史調整記錄

- 2026-07-30 的原始排程曾將 PDF／論文、特定社群平台、圖片 OCR、NotebookLM、標籤篩選與遠端部署並列為四週必做範圍。
- 2026-08-09 依核准設計規格修正為三來源核心 MVP；PDF／論文、OCR 與標籤篩選改為選配，遠端部署、YouTube、社群與正式分類器改由後續里程碑完成。
- 本清單保留上述歷史改動，但完成狀態以實際通過驗證的成果為準。

## Task 5: one-command publishing (2026-08-14)

- [x] 新增 `scripts/publish_url.py`，以固定 repo / Pages / workflow 預設值組合本機 one-command publishing 流程。
- [x] 新增 `tests/test_publish_url_script.py`，覆蓋單一 URL 參數、成功輸出、安全錯誤、subprocess `shell=False` 與固定 User-Agent。
- [x] 更新 `README.md`，記錄 `publish_url.py` 的 `.venv` 與已啟用 venv 兩種執行方式。
- [x] 以使用者核准的 `https://henyahouse.com/python-learning-path/` 完成 Task 5 creation-path 端到端驗收；摘要 commit `5dfd87e24158ec4226c44a09a32c659b5fa1a197`、workflow run `31797946291` 與公開列表／詳情頁均已驗證。
- [x] 以不經網路安裝的本地既有前端依賴完成 Task 5 frontend gates：Vitest 24 passed、Astro check 0 errors/0 warnings/0 hints、Pages build 3 pages、build:pages internal dist verifier passed、`python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/` exit 0。

## Provider configuration update (2026-08-13)

- [x] Provider-aware CLI composition: Gemini is the default; OpenAI is explicit; only the selected provider key is required; there is no automatic fallback; `list`, `show`, `archive`, and `publish` are key-free.
- [x] Automated provider configuration coverage completed; the full Python suite passed 132 tests.
- [x] Migrated the Gemini default to stable `gemini-3.6-flash`; full Python automation passed 133 tests and the user-approved live acceptance completed on 2026-08-14.

## 首頁編輯雜誌風與完整 OG 縮圖（2026-08-28）

- [x] 將最新已發布摘要呈現為編輯雜誌風精選卡片，並維持所有摘要共用既有搜尋、分類及排序流程。
- [x] 首頁 OG 圖使用固定 `1200:630` 展示框與 `object-fit: contain`，不裁切、不拉伸。
- [x] 所有一般與精選卡片可見來源名稱；優先顯示作者，否則以 `YouTube`、`社群貼文`、`公開網頁` 顯示，並與圖片 fallback 共用同一個標示。
- [x] 完成三／二／一欄響應式排版與可見鍵盤焦點；Edge 1280 確認 7/7 卡片可見來源、精選文字左／圖片右，390 確認精選文字第 1 列、圖片第 2 列且 `Bluesky` 來源可見，均無溢出。
- [x] 通過相關 Vitest（focused 2 files, 39 passed；完整 6 files, 63 passed）、Astro check、正式 `build:pages`（8 pages、deployment verifier exit 0）及本機 Edge 瀏覽器驗收；程式 head `058b386`，所有卡片圖片 `loading="lazy"` 經使用者核准保留。
- [x] 圖片 fallback 保留既有 source-contract 覆蓋；Edge failed-image 獨立模擬尚未執行，不宣稱已完成該瀏覽器情境。
- [x] 將首頁功能 fast-forward 合併至本機 `master`，並成功 push 功能 head `c91cb3f` 至 `origin/master`。
- [x] 完成本次首頁變更的 Pages workflow 驗收：Run #35（`33210585948`）對應 `caa9df6`，completed successfully。
- [x] 完成遠端首頁 1280／800／390px 響應式、OG 小圖 contain、來源顯示、搜尋、分類、排序、無結果與鍵盤焦點驗收。
- [x] 修正 failed-image fallback 的本機實作並完成驗證：完整 Vitest 為 7 個檔案、67 tests passed；Astro check 0 diagnostics、靜態建置 8 pages，內部與 tracked/dist deployment verifier 均 exit 0。
- [x] 部署並驗收最新 failed-image fallback 修正：保留 `fa00277`／Run #37 曾以 `display:none` 阻止 Chrome 與 Edge lazy-load 的回歸紀錄；`338b17f` 改用 `opacity:0` 且保留 `display:block`，包含該修正的 `f8658c5` 已由 Pages Run #38（`33238303280`）成功部署。遠端 Chrome 封鎖圖片時 7/7 圖片為 `pending`、0×0、`currentSrc=""`、`display="block"`、`opacity=0`，7/7 fallback 可見、全頁截圖無破圖、1920 viewport 無水平溢出；恢復權限並重整後 7/7 圖片為 `loaded`、1200×630、`currentSrc` 有效、`display="block"`、`opacity=1`、`object-fit: contain`，且無水平溢出。
