# AI Digest 專案進度

> 最後更新：2026-08-09
>
> 專案期程：2026-07-31～2026-08-27（四週，不含企畫日）
>
> 目前階段：GitHub Pages workflow 與完整本機部署 gate 已驗證；真實遠端 deployment、公開 smoke 與真實來源驗收尚未執行
>
> 下次續作：先執行並驗收真實 GitHub Pages deployment 與公開 smoke，再由使用者提供核准的公開文章 URL 與本機 OpenAI 憑證完成真實來源驗收

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
| 公開網頁本機里程碑 | 自動化驗證已完成 | URL 安全檢查、擷取、摘要邊界、開發用分類器、Schema、原子 JSON 儲存、CLI 與 Astro 已串接 |
| 公開網頁真實來源驗收 | 未驗證 | 未提供使用者核准 URL 與 OpenAI 憑證；不以任意網址代替 |
| 分類模型與評估 | 尚未開始 | 現有 `FixedClassifier` 僅供開發串接；正式模型必須嚴格優於最大類基準 |
| YouTube 公開影片 | 尚未開始 | 有字幕與無可用字幕都屬後續核心 MVP |
| 公開社群單篇貼文 | 尚未開始 | 不繞過登入、存取控制或私有內容限制 |
| GitHub repository 與 Pages | 本機就緒／遠端未驗證 | workflow、base path、artifact verifier、bounded smoke checker 與完整本機 gate 已通過；真實 deployment 與公開 smoke 為 **UNVERIFIED** |
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
- [x] OpenAI 結構輸出驗證失敗時不會寫入不完整資料。
- [x] Astro 能驗證資料並建置首頁與獨立詳情頁，提供搜尋、分類篩選與日期排序。
- [x] 已執行追蹤檔案憑證格式掃描與差異空白檢查。
- [ ] 使用一個由使用者提供並核准的真實公開文章與本機 OpenAI 憑證完成端到端驗收。

## 已知風險、阻礙與設定注意事項

| 項目 | 目前處理原則 |
|---|---|
| 公開來源受付費牆、登入或反爬蟲限制 | 不嘗試繞過，回報明確的結構化錯誤 |
| 真實網頁與 OpenAI 驗收 | 尚缺使用者核准 URL 與憑證，明確記錄為未驗證 |
| 開發用固定分類器 | 只用於管線串接，不視為分類模型完成 |
| Python CLI `PATH` | 目前 user-site Scripts 目錄未在 `PATH`；建議啟用 `.venv`，或明確加入對應 Scripts 目錄 |
| npm 安裝 script | `esbuild@0.28.2` 與 `esbuild@0.25.12` 仍有未核准安裝 script 通知；本里程碑未授權它們 |
| npm advisory audit | 本次唯一 `npm audit --json` 嘗試因 registry endpoint 無法連線而無 advisory 結果，保持 **UNVERIFIED**，不得宣稱零漏洞 |
| GitHub Pages 遠端驗收 | workflow 與本機 gate 已完成；尚未觸發真實 deployment 或對公開網址執行 smoke acceptance |
| YouTube 與社群平台變動 | 各來源保持獨立解析器，於對應里程碑以真實案例驗證 |
| 摘要或分類正確性 | 保留原文連結，分類器完成前不宣稱模型效能 |

## 進度紀錄

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

1. 取得使用者對一個可直接讀取公開文章 URL 的明確核准，並由使用者在本機提供 OpenAI 憑證。
2. 執行真實公開網頁 `add`，確認各階段輸出、合法 JSON 與無憑證外洩。
3. 重新建置 Astro，確認新資料的詳情頁出現於 `site/dist`。
4. 觸發 GitHub Pages workflow，驗證真實 deployment 與公開 smoke；完成前保持 **UNVERIFIED**。
5. 遠端部署驗收後，再進入分類資料標註與可重現評估、YouTube 及公開社群里程碑。

## 更新規則

每次工作結束後，在「進度紀錄」最上方新增日期與完成事項，並同步更新整體階段、驗收勾選、`todo.md`、風險與重要決策。只能勾選已實際完成且通過相稱驗證的項目。
