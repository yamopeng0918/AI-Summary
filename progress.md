# AI Digest 專案進度

> 最後更新：2026-08-28
>
> 專案期程：2026-07-31～2026-08-27（四週，不含企畫日）
>
> 目前階段：YouTube 真實案例與每筆已發布摘要的 OG PNG、metadata、卡片顯示及 GitHub Pages 遠端驗收均已完成
>
> 下次續作：進入核心 MVP 的公開社群單篇貼文設計；不得擴張到登入內容、私人內容、完整討論串或網站後台

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
| 分類模型與評估 | 已完成 | 180 筆已核准、六類各 30 筆；固定 144/36 分層切分的 Accuracy 0.9167、Macro F1 0.9179，嚴格高於最大類基準 0.1667，production artifacts 已驗證 |
| YouTube 公開影片 | 已完成 | Gemini Files API 轉錄、安全遠端清理、單一 provider 路由與有限 delete 重試已完成；2026-08-26 核准有字幕與無字幕案例均完整到達 `complete`，通過資料驗證並確認本機／遠端零殘留 |
| 公開社群單篇貼文 | 尚未開始 | 不繞過登入、存取控制或私有內容限制 |
| GitHub repository 與 Pages | 已完成 | Pages Source 已設為 GitHub Actions；既有遠端部署已驗收，本機 `build:pages` 現會為每筆 `published` 摘要產生 OG PNG，並串接卡片與詳情頁 metadata |
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
| 正式分類器 artifact | 生產流程只載入 repository 控制的 joblib 與 manifest；缺檔、版本或分類順序不符時 fail closed，沒有 `FixedClassifier` fallback |
| Python CLI `PATH` | CLI 已安裝於 `.venv\Scripts`；目前 PowerShell 可透過直接執行 `.\.venv\Scripts\ai-digest.exe`，或將該目錄加入目前 process `PATH` 後使用 `ai-digest`。尚未宣稱已持久修改互動使用者的 `PATH` |
| npm 安裝 script | `esbuild@0.28.2` 與 `esbuild@0.25.12` 仍有未核准安裝 script 通知；本里程碑未授權它們 |
| npm advisory audit | 後續可連線驗證已完成；`npm audit --json` 回報各嚴重度均為 0 漏洞 |
| 憑證 grep 已知基準警告 | Task 7 規定的寬鬆 `git grep` 式子回傳 exit `0`並命中 9 處既有計畫文件、placeholder 與故意的安全測試字串；這是尚未排除的 false-positive baseline。實際 deployment verifier 對 tracked 與 `site/dist` 掃描為 exit `0`，本次 diff 也未包含真實金鑰、Cookie 或憑證值 |
| YouTube 本機工具與手動驗收 | 2026-08-26 已使用 `yt-dlp 2026.08.19`、`FFmpeg 9.0.1`、`gemini-3.6-flash` 與使用者核准的有字幕／無字幕公開影片完成兩案驗收；兩案均 exit 0、到達 `complete`、通過資料驗證，且本機媒體與 Gemini Files 均為 0 |
| GitHub Pages 遠端驗收 | Pages `build_type=workflow`；run `33134830540` 已成功部署 commit `c17e3ae`，並通過 workflow 內 smoke 與獨立公開 OG 驗收 |
| OG 圖建置 artifact 與字型 | `site/dist/og/` 由建置重新產生且不納入 Git；renderer 納管官方完整 Pan-CJK Regular／Bold 靜態 OTF 與 OFL-1.1，並在渲染前執行 fail-closed cmap 覆蓋檢查。功能已合併、push 並完成 GitHub Pages 遠端驗收 |
| YouTube 與社群平台變動 | 各來源保持獨立解析器，於對應里程碑以真實案例驗證 |
| 摘要或分類正確性 | 保留原文連結，分類器完成前不宣稱模型效能 |

## 進度紀錄

### 2026-08-28：Pages workflow 與公開 OG 圖遠端驗收

- `master` push 已自動觸發 Pages workflow；commit `c17e3aea90f874a1e135d24b8f9d979d1c9ca50e` 對應 run [`33134830540`](https://github.com/yamopeng0918/AI-Summary/actions/runs/33134830540)，GitHub API 回報 `status=completed`、`conclusion=success`。前一個合併提交 `8891ae0` 的 run `33134643404` 亦為 success。
- 重新執行既有 `scripts/smoke_pages.py`，公開首頁與 demo 詳情頁均可讀取，exit 0。
- 另以獨立 HTTP 驗收逐筆檢查全部 `6` 筆 published 摘要：首頁 HTTP 200；`6/6` 詳情頁 HTTP 200；`6/6` OG PNG HTTP 200、`Content-Type: image/png`、PNG signature 有效且尺寸皆為 `1200×630`。
- 首頁 `6/6` 卡片圖片路徑均指向對應 `/AI-Summary/og/<encoded-id>.png`；每個詳情頁的 `og:image` 與 `twitter:image` 均為同一張絕對 HTTPS 圖片 URL，且 `og:image:width=1200`、`og:image:height=630`。
- 本次只讀取公開 GitHub API 與 Pages 資產，未使用憑證或輸出頁面原文；遠端 OG 功能驗收狀態由未驗證更新為完成。

### 2026-08-28：OG 圖合併與 GitHub 同步

- `feature/summary-og-images` 已以 merge commit `8891ae0` 合併至本機 `master`；合併衝突只涉及 `progress.md`，已同時保留 2026-08-26 CLI 診斷與 2026-08-27 OG 驗收紀錄。四個既有使用者未追蹤檔案未被加入、修改或刪除。
- 合併後重新執行完整 gates：Python `501 passed, 2 skipped, 1 warning`（兩個 skip 為目前 Windows 帳號無 symlink 建立權限，warning 為既有 `google.genai` deprecation）；Vitest `47 passed`；Astro check `17 files`、`0 errors / 0 warnings / 0 hints`；Pages build `7 pages` 並生成 `6` 張 OG PNG；embedded 與獨立 tracked／dist verifier、`git diff --check` 均 exit `0`。
- `master` 已 push 至 GitHub，重新 fetch 後確認本機 `HEAD` 與 `origin/master` 皆為 `8891ae0f236bf1a58024123c37a824d1d14d01b5`。第一次 push 已在遠端完成但本機未收到結束回應，第二次重試因此收到 remote ref 已前進的拒絕；fetch 後確認沒有分歧或資料遺失。
- 尚未對此次 push 觸發的 GitHub Actions／Pages 結果及公開 OG 圖 URL 執行獨立遠端驗收，因此不得宣稱遠端部署已通過；本機建置與 GitHub repository 同步已完成。

### 2026-08-27：每筆摘要 OG PNG 最終驗收

- 每筆 `published` 摘要的 `1200×630` PNG、首頁卡片顯示，以及詳情頁 `og:image`／`twitter:image` metadata 已完成；`site/dist/og/` 保持為建置 artifact，不納入追蹤內容。
- 字型已改為官方完整 Pan-CJK `NotoSerifCJKtc-Regular.otf`（400）與 `NotoSerifCJKtc-Bold.otf`（700），保留 OFL-1.1 且不在正常測試／建置下載；渲染前逐字檢查 assigned-weight cmap，精確回歸字元 `级`、`战`、`术`、`来` 均有字形。標題／摘要／來源分別採 `18`／`40`／`36` 個全形等價字元上限，fitted 行強制 `nowrap`；分類位於右上，footer 只保留有界來源與大寫來源類型。
- 完整 gates：focused frontend `4` 個測試檔、`20 passed`；focused deployment verifier `53 passed`；完整 Python `488 passed, 1 warning`（既有 `google.genai` deprecation）；完整 Vitest `6` 個測試檔、`47 passed`；Astro check `17 files`、`0 errors / 0 warnings / 0 hints`；Pages build `7 pages`；獨立 tracked／dist deployment verifier 與 `git diff --check` 均 exit `0`。
- Final re-review 已將 generic image 與 summary-card 解析集中至同一個 fail-closed resolver：percent／反斜線正規化與 `resolve()` 後，必須先通過 resolved `dist_root` containment 才可探測或開啟檔案，因此 traversal、encoded absolute path 與 symlink escape 都不會讀取外部目標。PNG scanline bookkeeping 改為非交錯一組、Adam7 最多七組 `(row_bytes, row_count)`，並在解壓前以算術上限拒絕 `height=0xffffffff` 等惡意 IHDR；另以真實 CRC／zlib fixture 覆蓋非連續 IDAT、錯誤 scanline 長度與非法 row filter。
- Re-review gates：focused deployment verifier `60 passed, 1 skipped`（目前 Windows 帳號無建立 symlink 權限，支援 symlink 的環境會執行該測試）；完整 Python `495 passed, 1 skipped, 1 warning`；完整 Vitest `6` 個測試檔、`47 passed`；Astro check `17 files`、`0 errors / 0 warnings / 0 hints`；Pages build `7 pages`；獨立 tracked／dist verifier、六筆 metadata/card mapping、Sharp `6/6` PNG `1200×630` audit 與 `git diff --check` 均 exit `0`。
- 最終 whole-branch follow-up 將 `main --dist` 的敏感資料掃描也納入 containment-first 全樹 inventory：每個 candidate 在 `is_file()`／`read_bytes()`／HTML `read_text()` 前先解析並證明位於 resolved `dist_root` 內；escape、root／entry inspection 或 read failure 都回傳穩定 violation 並中止後續讀取。掃描同時保留 lexical candidate 名稱，因此指向內部安全 target 的 `.env` alias 仍會被拒絕。
- Follow-up gates：focused deployment verifier `66 passed, 2 skipped`；完整 Python `501 passed, 2 skipped, 1 warning`；完整 Vitest `6` 個測試檔、`47 passed`；Astro check `17 files`、`0 errors / 0 warnings / 0 hints`；Pages build `7 pages`；embedded 與獨立 tracked／dist verifier 均 exit `0`；六筆 metadata/card mapping 全部為 `2/1`，Sharp `6/6` PNG 均為 `1200×630`；獨立 code re-review 結論為 Ready，沒有剩餘 Critical／Important finding。兩個 skip 都是目前 Windows 帳號 WinError 1314 無 symlink 權限，支援環境會正常執行。
- Artifact audit：`6` 筆 published 對應 `6` 張 PNG；`6/6` PNG signature、Sharp format 與 `1200×630` 尺寸正確；`6/6` 詳情頁兩種圖片 metadata 均解析至對應 PNG；archived 記錄 `0`、archived PNG `0`。
- 全部 `6/6` 實際 PNG 均以原始解析度逐張檢視，必要時另以完整畫布檢視確認邊界：米白／珊瑚／深綠編輯色與文字對比清楚，所有中英文字形可讀，沒有 tofu、裁切或溢出；每張分類均在右上，來源在左下，大寫來源類型在右下。
- 風險：本次只驗證本機 branch，未 push、未觸發遠端 Pages 部署；未來替換字型時必須維持兩個完整 Pan-CJK 靜態 OTF、OFL-1.1 與 cmap regression 成對更新。
- 下一步：依既定核心 MVP 順序進入無須登入的公開社群單篇貼文設計，不擴張至登入／私人內容、完整討論串或網站後台。

### 2026-08-26：CLI 重複 URL 與記錄查詢診斷

- 操作員以既有 TechOrange canonical URL 執行 `ai-digest add` 時收到 `DUPLICATE_URL`；確認這是規格要求的重複建立保護，既有記錄未被覆寫或刪除。
- `ai-digest show` 的 `RECORD_NOT_FOUND` 並非資料遺失：輸入值包含 `ai-digest list` 輸出的整列 ID、標題、分類與狀態，而 `show` 只接受第一欄的精確記錄 ID。
- 已用精確 ID `20260814-always-be-coding-工程師面試必讀-techorange-科技報橘-7374d398` 實際執行 `ai-digest show`，exit 0 並成功載入完整 JSON。此項屬操作診斷，未修改 CLI 行為、資料或 `todo.md` 完成狀態。

### 2026-08-26：Windows CLI PATH 修正

- 重現 `ai-digest` 為 `CommandNotFoundException`：CLI 已正確存在於 `D:\Project\AI-Summary\.venv\Scripts\ai-digest.exe`，但目前 PowerShell 未啟用虛擬環境，且 Execution Policy 阻擋 `Activate.ps1`。
- 不修改 Execution Policy；已驗證直接執行 `.\.venv\Scripts\ai-digest.exe`，以及把 `.venv\Scripts` 加到目前 process `PATH` 後裸用 `ai-digest list`／`--help`，均 exit 0。受控環境無權寫入互動使用者的登錄 PATH，因此未宣稱持久修改；README 已補充兩種可立即使用的安全方式。

### 2026-08-26：YouTube 分支合併與 GitHub 同步

- `feature/provider-aligned-transcription` 已 fast-forward 合併至本機 `master`，YouTube 里程碑完成提交為 `01bdec7`；合併前已執行 `git pull --ff-only origin master` 並確認遠端沒有新提交。
- 合併後的新鮮 gates：完整 Python `453 passed, 1 warning`；Schema/storage `28 passed`；Vitest `25 passed`；Astro `0 errors / 0 warnings / 0 hints` 並建置 `5 pages`；deployment verifier、`git diff --check` 與 `site/dist` 媒體掃描通過。
- `master` 已成功 push 至 GitHub，YouTube 里程碑由 `7cc0451` 前進至 `01bdec7`，其後進度紀錄提交 `5b846ed` 也已同步；本機 `HEAD` 與 `origin/master` 已核對一致。主工作區既有 4 個未追蹤使用者檔案未被加入、修改或刪除；未建立 Pull Request，也未手動部署 GitHub Pages。
- 已合併的 feature worktree 因既知 `.pytest-task2-basetemp/` 權限／未追蹤內容而被非強制 `git worktree remove` 拒絕；沒有使用 `--force`。`feature/provider-aligned-transcription` 與該 worktree 暫時保留，僅屬本機清理事項，不影響 `master`、GitHub 同步或已完成驗收。

### 2026-08-26：核准 YouTube 雙案例驗收

- 使用者提供並核准有字幕案例 `https://www.youtube.com/watch?v=xFPiU5sit7g`，並明確核准對既有無字幕案例 `https://www.youtube.com/watch?v=4gciWspBVHw` 再執行一次 Gemini 付費驗收。兩次均使用新的隔離目錄，CLI 原始輸出不落盤，只記錄去識別化階段、錯誤碼與退出狀態。
- 有字幕案例 exit 0，階段為 `input, extract, summarize, classify, validate, save, complete`，無錯誤碼、無未解析輸出。唯一 JSON 通過 `SummaryRecord`、YouTube、精確 canonical URL、`published`、非空 summary/editorial、3～5 key points、含時區時間、零禁止標記與零媒體檢查；Gemini Files 中間計數為 0，驗證後只刪除精確隔離 root。
- 無字幕案例 exit 1，階段為 `input, extract, extract`，錯誤碼 `TRANSCRIPTION_FAILED`，未到 `complete` 且無未解析輸出。依核准停止規則沒有重跑；失敗後精確 isolation root 不存在，JSON、媒體與其他檔案均為 0，Gemini Files 唯讀計數為 0。
- 有字幕真實驗收已完成；無字幕此次僅證明 fail-closed 與清理成功，未證明端到端成功。整體「有字幕與無字幕各一例」及無字幕隔離驗收仍維持未勾選，新的付費嘗試需另行決定。
- 記錄更新後的新鮮 gates：完整 Python `453 passed, 2 warnings`；Schema/storage `28 passed, 1 warning`；Vitest `25 passed`；Astro `0 errors / 0 warnings / 0 hints` 並建置 `5 pages`；deployment verifier、`git diff --check` 與 `site/dist` 媒體掃描通過，兩個精確驗收 root 均不存在。
- 後續唯讀診斷確認無字幕案例為公開、非直播、2292 秒、沒有人工或自動字幕，依 600 秒設定預期切成 4 個 chunk；轉錄模型仍為 `gemini-3.6-flash`。`MEDIA_DOWNLOAD_FAILED` 與實際 `TRANSCRIPTION_FAILED` 的錯誤邊界證明流程已進入轉錄建立／請求／回應／清理範圍，但該 code 同時涵蓋四種安全訊息。上一輪只保存 code、未保存安全 `message`，因此現有證據不足以區分 configuration、request、invalid response 或 cleanup；不得臆測根因或直接修改。下一個有判別力的步驟是取得明確付費重試核准後，只額外保存既有安全 `message`、stage、code、retryable 與 exit，不保存原始 SDK 錯誤或敏感資料。
- 使用者後續明確改回付費方式並核准重試；新隔離 root 與 Gemini Files pre-count 均為 0。無字幕案例 exit 0，階段 `input, extract, summarize, classify, validate, save, complete`，無錯誤事件及未解析輸出。唯一 JSON 通過 `SummaryRecord`、精確 canonical URL、`published`、非空 summary/editorial、3～5 key points、含時區時間、零禁止標記與零媒體檢查；Gemini Files post-count 為 0，驗證後只刪除精確 root。至此有字幕與無字幕真實案例驗收均完成。
- 里程碑完成後的新鮮 gates：完整 Python `453 passed, 2 warnings`；Schema/storage `28 passed, 1 warning`；Vitest `25 passed`；Astro `0 errors / 0 warnings / 0 hints` 並建置 `5 pages`；deployment verifier、`git diff --check` 與 `site/dist` 媒體掃描通過，驗收 root 不存在。

### Gemini Files 清理有限重試設計（2026-08-25）

- adapter 內已實作固定有限重試：只重試 `files.delete()`，最多三次，暫時性失敗後等待 1 秒與 2 秒；timeout、transport、429 與 5xx 可重試，404 視為已達成清理，其他 4xx 與一般錯誤立即失敗。
- 既有主要錯誤優先、安全訊息、無部分逐字稿及中斷傳播規則保持不變；沒有新增環境變數、CLI 選項、SDK 全域重試、背景工作、帳號級 Files 掃描或跨 provider fallback。
- 2026-08-26 fresh controller gates：完整 Python `453 passed, 2 warnings`；Schema/storage `28 passed, 1 warning`；Vitest `25 passed`；Astro `0 errors / 0 warnings / 0 hints`、`5 pages`；`git diff --check` 與 tracked/`site/dist` deployment verifier exit 0；`site/dist` 媒體殘留 0。warnings 為 google-genai deprecation 與既有 pytest cache path 問題。
- 2026-08-26 final reviewer 補齊不必要 retry／等待的自動化證據：`tests/test_gemini_transcriber.py` 為 `32 passed, 2 warnings`，明確覆蓋 first-success、cleanup HTTP 400、unexpected cleanup exception，以及成功／主要一般錯誤交叉的 `KeyboardInterrupt`／`SystemExit` cleanup；所有不應重試的案例均記錄 `sleeper=[]`，且安全錯誤不洩漏敏感標記。此為本機 coverage 補強，不改變 live acceptance blocked 狀態。
- `yt-dlp 2026.08.19`、FFmpeg `9.0.1` 與不輸出值的 Gemini key 檢查均成功。Gemini Files 非識別性 pre/post 計數記錄均為 0；沒有列印或刪除帳號中其他 File。
- 操作員回報一次核准無字幕 URL live 嘗試使用 `gemini-3.6-flash`，且沒有授權或執行重跑；但沒有保留可持久的 CLI stage、exit 或執行計數 artifact，故不得把該嘗試或其原因視為獨立驗證事實。2026-08-26 controller 在精確 isolation root 發現一個 JSON、零媒體，並以不輸出 record/ID/title/raw JSON 的布林檢查確認：YouTube、核准 canonical URL、`published`、非空 summary/editorial、3～5 key points、含時區時間，以及零 repository/media/Files/Gemini URI 禁止標記。ai-digest/yt-dlp/ffmpeg process 計數為 0、Gemini Files current count 為 0；controller 確認 root 不變後只刪除該精確 root，現已不存在。record `createdAt` `2026-08-25T22:43:02.489095+08:00` 早於 22:50:42 的首次 docs commit；directory/file creation `2026-08-25T22:52:53+08:00` 晚於該 commit 且早於 22:56:22 的 wording-correction commit。此序列與先前過早 filesystem check 後的延遲／非同步完成相容，但不證明因果、CLI stage／exit 或執行計數。缺少 `complete` stage／exit 證據且有字幕案例仍缺，因此狀態維持 `Implemented; live acceptance blocked`，下次需新的明確決定。

### Provider-aligned 音訊轉錄 Task 4 自動化收尾（2026-08-25）

- `.env.example` 與 README 已改用 `GEMINI_TRANSCRIPTION_MODEL=gemini-3.6-flash`、`OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe`；`AI_DIGEST_PROVIDER` 同時選擇摘要與無字幕轉錄，只有所選 provider 金鑰需要設定，沒有跨 provider fallback。
- README 已記錄 Gemini Files API 的逐段上傳與遠端清理生命週期，OpenAI 路徑仍保留；舊 YouTube 設計頂端已連結 2026-08-22 provider-aligned 設計並標示原 OpenAI-only 決策被部分取代。
- 完整 Python suite 為 `444 passed`，只有既存 google-genai／Python 3.14 `DeprecationWarning`；Vitest `25 passed`；Astro check 為 `0 errors / 0 warnings / 0 hints`，正式建置 `5 pages`；Schema/storage 專項 `28 passed`。
- `git diff --check`、tracked／`site/dist` deployment verifier 與建置輸出媒體殘留掃描均通過，`site/dist` 未發現 `.mp3`、`.m4a`、`.webm`、`.vtt` 或 `.srt`。
- 先決條件檢查只回報布林狀態、不輸出金鑰：`yt-dlp=False`、`ffmpeg=False`、`gemini_api_key=True`。因此沒有對核准的無字幕影片 `https://www.youtube.com/watch?v=4gciWspBVHw` 發起網路或 Gemini API 呼叫，沒有建立驗收 JSON，也沒有產生需清理的驗收目錄；實際 Gemini 轉錄模型尚未送出請求，設定預設值為 `gemini-3.6-flash`。
- repository 目前沒有足以證明先前有字幕真實驗收之 URL 與有效紀錄；加上本次無字幕驗收受阻，`todo.md` 的「有字幕與無字幕各一例」維持未勾選。下一核心實作仍是公開社群單篇貼文，但 YouTube 真實驗收技術債必須在工具備妥後回補。

### Provider-aligned 無字幕真實驗收嘗試（2026-08-25）

- 以 Chocolatey 安裝 `FFmpeg 9.0.1`，並確認既有 `yt-dlp 2026.08.19`、`GEMINI_API_KEY` 與網路先決條件可用；使用的摘要與轉錄模型皆為預設 `gemini-3.6-flash`。
- 核准無字幕案例 `https://www.youtube.com/watch?v=4gciWspBVHw` 第一次執行完成至 `save` 並產生唯一 JSON。`SummaryRecord` 驗證、`sourceType=youtube`、canonical URL、`published`、非空摘要與編輯觀點、3～5 個重點及敏感／媒體痕跡掃描全部通過，且本機沒有媒體殘留；CLI 僅在 CP950 終端輸出包含不可編碼紀錄 ID 的 `complete` JSON 時失敗。
- 依 TDD 新增非 UTF-8 Windows console 回歸測試，先以相同 `UnicodeEncodeError` RED，將結構化事件改為 ASCII-escaped JSON 後 GREEN；CLI 專項 `38 passed`，完整 Python suite `445 passed`。Vitest `25 passed`，Astro `0 errors / 0 warnings / 0 hints`、正式建置 `5 pages`，deployment verifier 與媒體掃描通過。
- 清除第一次隔離資料後重跑端到端驗收，流程在 Gemini Files 刪除時以安全錯誤 `TRANSCRIPTION_FAILED / Audio transcription cleanup failed` 停止，沒有保存第二份 JSON。沒有盲目第三次重試；Gemini Files 唯一遺留音訊依建立時間、`audio/mpeg` MIME 與大小精確識別、刪除，並確認 Files 清單為 0。
- 因第二次執行未到達 `complete`，且既有有字幕案例仍缺完整有效證據，`todo.md` 的整體真實案例驗收維持未勾選。下一步是先設計並核准有限、可測試且不掩蓋主要錯誤的 Gemini Files 刪除重試策略，再重跑一次隔離驗收。

### Provider-aligned 音訊轉錄 Task 1～3（2026-08-22）

- 核准設計與實作計畫已建立；工作在隔離分支 `feature/provider-aligned-transcription` 進行，未 push、合併或部署。
- Task 1 提交 `8e38e61`：新增 `GeminiAudioTranscriber`，依序上傳音訊 chunk、呼叫 Gemini 逐字轉錄、刪除每個遠端檔案並合併完整結果；缺少 `GEMINI_API_KEY` 時在 client 建構前安全失敗。
- Task 2 提交 `c4d88e4`：補齊畸形／空白回應拒絕、timeout／rate limit／transport／SDK／本機錯誤映射、無部分結果、成功／失敗／中斷清理、雙重失敗主要錯誤優先及敏感資訊不洩漏。Gemini 與既有 OpenAI transcriber 專項為 `39 passed`。
- Task 3 提交 `b779286`：`AI_DIGEST_PROVIDER` 現在同時選擇摘要器與無字幕音訊轉錄器；Gemini 與 OpenAI 各只使用自己的金鑰及 `GEMINI_TRANSCRIPTION_MODEL`／`OPENAI_TRANSCRIPTION_MODEL`，不自動 fallback，舊 `AI_DIGEST_TRANSCRIPTION_MODEL` 不再由正式程式讀取。CLI、YouTube、media 與兩 provider transcriber 測試為 `177 passed`。
- 以上驗證均使用 fake client 與本地 fixture，沒有呼叫外部網路、媒體工具或付費 API；只有既存的 google-genai／Python 3.14 `DeprecationWarning`。Task 4 的 `.env.example`、README、舊設計 supersession note、完整 Python／前端／建置／部署驗證及真實無字幕 Gemini 驗收尚未執行，因此不得宣稱 provider-aligned 里程碑完成。

### YouTube 本地自動化里程碑（2026-08-21）

- 已依 TDD 擴充 Astro 前端契約：focused RED 為 `21 passed / 1 failed`，失敗原因是 Zod 將 `sourceType: youtube` 拒為非 `web`；將 TypeScript 與 Zod 同步擴充為 `web | youtube` 後，focused GREEN 為 `22 passed`。
- 完整本地自動化驗證：Python `396 passed`，但仍有 1 個既有 Google SDK `DeprecationWarning`；Vitest `25 passed`；Astro check 為 `0 errors / 0 warnings / 0 hints`，正式建置完成 `5 pages`。
- portable Schema 與 storage 專項 `16 passed`；`site/dist` 無 `.mp3`、`.m4a`、`.webm`、`.vtt` 或 `.srt` 檔案，deployment verifier 與 `git diff --check` 通過。規定的寬鬆 `git grep` 因 9 處既有文件／測試字串命中，作為 false-positive baseline 警告保留，不謊稱為無命中。
- 本機沒有 `yt-dlp` 與 FFmpeg，且未設定無字幕轉錄需要的 `OPENAI_API_KEY`；因此未呼叫真實網路或 API，有字幕與無字幕影片的手動整合驗收均保持 **UNVERIFIED**。
- `npm ci` 依賴已由上階段準備且 audit 為 0 vulnerabilities，但 `esbuild@0.28.2` 與 `esbuild@0.25.12` 仍有未核准 install-script 通知，本次未核准或執行該 scripts。
- 下一核心實作里程碑為公開社群單篇貼文；YouTube 手動驗收在必要工具、金鑰與網路備妥後仍需回補，不得以自動化替代。

### Task 8 正式分類器驗收（2026-08-21）

- 最終 cohort 共 180 筆 approved 資料，六類各 30 筆；dataset SHA-256 為 `1b65281c6dda2a60b800442140129915ff84d292da0e4fdfa69246b50544459c`，固定 seed `42` 的 split SHA-256 為 `0c0c6cd136656b06c543cad61641a568a0268cd015a6f67c90e5cf482d85497e`。
- 評估使用 144 筆訓練、36 筆 held-out 測試，每類 24/6。Accuracy 為 `0.9166666666666666`，Macro F1 為 `0.917915417915418`，最大類基準 Accuracy 為 `0.16666666666666666`；`beatsBaseline=true`、`accepted=true`。
- 依 `人工智慧`、`程式開發`、`科技產業`、`商業與職場`、`設計與創意`、`生活與學習` 順序，混淆矩陣為 `[[5,0,0,0,0,1],[0,6,0,0,0,0],[0,0,6,0,0,0],[0,0,0,5,0,1],[0,0,1,0,5,0],[0,0,0,0,0,6]]`。
- 使用 scikit-learn `1.9.0` 產生並獨立驗證 `data/classifier/split.json`、`data/classifier/evaluation.json`、`models/classifier.joblib` 與 `models/classifier-manifest.json`；六個代表文字均預測為對應配置分類。
- 完整 gates：Python `266 passed`、1 個既有 Google SDK 棄用警告；Vitest `24 passed`；Astro `0 errors / 0 warnings / 0 hints`；Pages build `5 pages`；tracked/dist deployment verifier exit `0`。
- 正式分類器分支已合併至 `master`，merge commit `f9977de` 已推送至 GitHub。合併結果重新通過 Python `266 passed`、Vitest `24 passed`、Astro `0 diagnostics`、Pages `5 pages`、tracked/dist deployment verifier 與 `git diff --check`。

### 分類器審核批次三來源修正（2026-08-20）

- 依審查發現逐一重新開啟 `b3-ai-006`、原 `b3-ai-008`、`b3-design-006` 與 `b3-design-008` 的來源頁面；Cohere 頁面缺少足以支撐原列的可讀正文，因此將 `b3-ai-008` 改為可直接讀取的 Mistral AI 文章 `Au Large`，其餘三列依可見正文收斂文字或修正標題。
- `b3-ai-006` 移除來源摘要未支持的「能力限制」；`b3-design-006` 的 `sourceTitle` 改為可見 H1 `Design systems with Penpot`；`b3-design-008` 移除無障礙宣稱，改為來源直接列出的可靠透明介面與低認知負荷。
- 四列仍維持 `pending` 且 `reviewNote` 留白。替換後 180 筆 ID 與 canonical URL 皆唯一，批次三人工智慧類仍有 8 個 registrable domains、10 筆新網域來源；最終 cohort、內容雜湊、模型訓練與正式評估仍未執行。

### 分類器審核批次三研究（2026-08-20）

- 新增批次三 60 筆候選資料：`人工智慧`、`程式開發`、`科技產業`、`商業與職場`、`設計與創意`、`生活與學習` 各 10 筆；ID 為 `b3-<category>-001..010`，全部維持 `pending` 且 `reviewNote` 留白。
- 逐一開啟每個最終採用的公開單篇來源，確認能直接讀取標題與足以支持繁體中文轉述的正文。Spotify 設計頁會重新導向播放器、兩篇 Harvard 文章直接存取回傳 403，均未納入；Cornell 的既有批次二 URL 也因重複而改用另一篇文章。
- 批次三每類使用 8～10 個 registrable domains，單一網域每類最多 2 筆；相較批次一、二，每類有 6～10 筆來自該類別未使用過的網域。已避開 DeepMind、Edutopia、Canva、web.dev 與 Apple。
- 目前資料集為 180 筆：批次一、二共 120 筆 `approved`，批次三 60 筆 `pending`；最終 cohort、內容雜湊、模型訓練與正式評估仍未完成，也未執行。

### 分類器審核批次一（2026-08-19）

- 完成人工研究與逐頁檢查 60 個公開單篇來源，依既定順序在 `人工智慧`、`程式開發`、`科技產業`、`商業與職場`、`設計與創意`、`生活與學習` 各建立 10 筆批次一候選資料；所有列均維持 `pending`，尚未核准或投入訓練。
- 可讀性檢查逐一開啟每個 HTTP(S) 頁面，確認能直接取得文章標題與足以判斷主題的正文，且不是登入牆、付費牆、反爬蟲畫面、分類／清單頁或重複 canonical URL；繁中 `text` 均為依正文撰寫的摘要性轉述，不保存頁面 dump 或大段原文。
- 初次獨立審查發現科技產業候選全數來自 Apple，且一筆職場候選的產品公告屬性造成分類歧義；修訂後科技產業改由 Apple、NVIDIA 與 Google 三個來源組成，職場候選則改為可直接判斷的團隊管理文章。批次一在人工智慧與生活與學習類別仍有較高出版者集中度，後續批次應優先增加來源多樣性，並在訓練前檢查出版者語彙造成的捷徑學習風險。
- 淘汰候選：MDN `javascript-console-methods` 與 Canva `tints-and-shades` 在個別開啟檢查時回傳內部錯誤，未納入資料；分別改用可直接讀取的 web.dev `Rendering performance` 與 NN/g `Design Thinking 101`。Atlassian `strategy/goal-alignment` 重新導向至 `innovation/goal-alignment`，CSV 使用最終網址。
- 新增 `docs/classifier-review.md`，規定既有列只修改 `reviewStatus`／`reviewNote`，退件修訂必須保留歷史並以新 ID 新增替代列。正式分類器資料集項目仍保持未完成，等待使用者逐列審核及後續兩個批次。

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
- The resumed acceptance then exposed a real Git return-code mismatch before staging: `git cat-file -e HEAD:<new-summary>` returns `128` when the JSON exists on disk but not in `HEAD`, while the mocked test had used `1`. The retained JSON was not staged or regenerated. TDD now covers the observed `128` result while preserving rejection of unexpected codes; the focused publishing suite passed `37` tests and acceptance remains safely resumable.
- Fresh creation-path acceptance completed successfully for `https://henyahouse.com/python-learning-path/`. The retained record `20260814-python-自學指南1-從零開始的學習路線-新手入門指南-henya-小屋-e3d0afda` was reused without another provider call, committed alone as `5dfd87e24158ec4226c44a09a32c659b5fa1a197`, and pushed to `master`. GitHub Actions run `31797946291` concluded successfully, and the one-command script verified both the public homepage listing and URL-encoded detail route.

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

1. 針對 2026-08-25 真實驗收觀察到的 Gemini Files 單次刪除失敗，先提出有限重試設計並取得核准；不得以無界重試、忽略清理錯誤或刪除帳號中其他 Files 作為修復。
2. 依 TDD 實作核准的清理策略並執行完整 Python、前端、建置、deployment verifier、敏感資料與媒體殘留 gates，再以 `https://www.youtube.com/watch?v=4gciWspBVHw` 重跑一次隔離無字幕驗收。
3. 只有端到端到達 `complete`、JSON 與本機／遠端清理都有證據，且有字幕案例也有有效紀錄時，才可勾選 YouTube 真實案例驗收；之後下一核心實作里程碑為公開社群單篇貼文。

## 更新規則

每次工作結束後，在「進度紀錄」最上方新增日期與完成事項，並同步更新整體階段、驗收勾選、`todo.md`、風險與重要決策。只能勾選已實際完成且通過相稱驗證的項目。

## Provider configuration update (2026-08-13)

- Provider-aware CLI composition is complete and automated tests cover the Gemini default, explicit OpenAI selection, invalid providers, selected-key validation, and key-free local commands.
- Gemini is the default (`GEMINI_API_KEY`, default model migrated to `gemini-3.6-flash` on 2026-08-14); OpenAI is selected explicitly (`OPENAI_API_KEY`, default model `gpt-5-mini`). There is no automatic fallback.
- Full Python automation passed: 133 tests. Gemini live acceptance completed on 2026-08-14 with the user-approved public article and a temporary repository.
### Task 7 classifier review batch 1 (2026-08-20)

- Applied the explicit user approval to the 60 batch-1 rows in `data/classifier/training.csv`: `b1-ai-001..010`, `b1-dev-001..010`, `b1-tech-001..010`, `b1-business-001..010`, `b1-design-001..010`, and `b1-life-001..010`. All are now `approved`; no rows were rejected or replaced.
- Validated the dataset loader and review counts: 60 approved batch-1 rows, ten per category, with unique IDs and source URLs. The remaining 120 examples, final 180-row cohort, and formal classifier training/evaluation remain incomplete.

### Task 7 classifier review batch 2 (2026-08-20)

- Applied the explicit user approval to the 60 batch-2 rows in `data/classifier/training.csv`: `b2-ai-001..010`, `b2-dev-001..010`, `b2-tech-001..010`, `b2-business-001..010`, `b2-design-001..010`, and `b2-life-001..010`. All are now `approved`; no rows were rejected or replaced.
- Validated 120 total approved rows: 20 per category and 60 in each of batches 1 and 2. There are no `pending` or `rejected` rows, the rejected-history count is zero, and all IDs and source URLs remain stable.
- Batch 3 research and review have not started. The final 180-row cohort, its content hash, classifier training, and formal evaluation remain incomplete.

### Task 7 classifier review batch 3 final approval (2026-08-20)

- Applied explicit approval to exactly 60 batch-3 rows (`b3-ai/dev/tech/business/design/life-001..010`); no other fields or rows changed.
- Final reviewed cohort: 180 rows, 30 per category, 60 per batch; 180 approved, no pending/rejected, unique IDs and canonical URLs.
- Dataset SHA-256: `1b65281c6dda2a60b800442140129915ff84d292da0e4fdfa69246b50544459c`.
- Classifier training/evaluation and model artifacts remain incomplete.

### YouTube source final integration verification (2026-08-22)

- Completed the approved public single-video YouTube ingestion scope: canonical URL handling, duplicate preflight, caption-first extraction, safe media fallback, OpenAI transcription, `sourceType: youtube` persistence, CLI routing, schema compatibility, and Astro rendering.
- Final security review approved the implementation after adding a 24 MiB pre-upload audio-chunk limit, sanitizing unexpected transcription and filesystem failures, preserving temporary-workspace cleanup, and deferring YouTube-only configuration validation until the YouTube route is selected.
- Fresh full verification passed: Python `416 passed` with one pre-existing google-genai/Python 3.14 deprecation warning; Vitest `25 passed`; Astro check reported 0 diagnostics and the production build generated 5 pages; `git diff --check` passed.
- Real public-video smoke tests for both caption and no-caption paths remain **UNVERIFIED** because this environment does not have yt-dlp/FFmpeg or a transcription API key. The corresponding `todo.md` acceptance item remains unchecked.
