# AI Digest 待辦清單

> 專案期程：2026-07-31～2026-08-27
>
> 最後同步：2026-08-13
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
- [x] 建立 OpenAI 結構化摘要邊界，驗證短摘要、3～5 個重點、1～5 個標籤與編輯觀點。
- [x] 確認摘要回傳不合格時不會寫入不完整資料。

### 管線與 CLI

- [x] 串接 URL 正規化、重複預檢、擷取、摘要、開發用分類與儲存。
- [x] 實作 `add`、`list`、`show`、`archive` 與 `publish` CLI 指令。
- [x] 以本地 HTML fixture、真實 `WebExtractor`、確定性摘要替身、`FixedClassifier` 與暫存 repository 完成 fixture-to-JSON 整合測試。
- [x] 驗證同一 URL 第二次新增被拒絕且檔案數不變。
- [ ] 取得使用者核准的公開文章 URL 與本機 OpenAI 憑證，執行一次真實來源驗收（**UNVERIFIED**）。

### Astro 本機網站

- [x] 建立已發布摘要卡片列表與獨立詳情頁。
- [x] 顯示短摘要、重點、分類、標籤、AI 編輯觀點、來源與原文連結。
- [x] 支援關鍵字搜尋、單一分類篩選與最新／最舊日期排序。
- [x] 忽略 `archived` 資料、處理無資料與無搜尋結果；資料驗證失敗時採 fail-closed，直接中止靜態建置。
- [x] 完成手機與桌面版基本響應式介面與本機靜態建置。
- [x] 建立 GitHub Pages workflow、`/AI-Summary/` base path、artifact verifier 與本機 `build:pages` gate。
- [x] 觸發真實 GitHub Pages deployment，並對公開首頁與 demo 詳情頁完成 smoke acceptance（最新 run `31674616177`，commit `7f7dc1ebd8fcb3e06ee79d748d5338f246aca0d1`）。

### 文件與安全收尾

- [x] 撰寫 Windows PowerShell 的 Python、CLI、測試、Astro 開發與靜態建置說明。
- [x] 記錄 `FixedClassifier` 僅供開發使用。
- [x] 記錄 user-site CLI `PATH` 注意事項與尚未核准的 esbuild 安裝 script 通知。
- [x] 執行 Python 與前端測試、Astro 正式建置、憑證格式掃描與 `git diff --check`。

## 後續核心 MVP

### 正式分類模型

- [ ] 建立 4～6 個互斥主分類的人工標註資料集與版本／內容雜湊。
- [ ] 以固定 random seed 訓練 TF-IDF 與 Logistic Regression 分類器。
- [ ] 儲存訓練／測試筆數、各類樣本數、Accuracy、Macro F1、混淆矩陣與標籤順序。
- [ ] 計算最大類基準 Accuracy，並驗證測試 Accuracy **嚴格高於**該基準後才標記分類模型完成。

### YouTube 公開影片

- [ ] 建立獨立 YouTube 來源解析器與公開影片存取驗證。
- [ ] 支援有可用字幕的公開影片。
- [ ] 支援無可用字幕影片的影音處理與轉錄流程。
- [ ] 處理驗證失效、限流、工具變動與中斷後可重試狀態。
- [ ] 有字幕與無可用字幕各以一個使用者核准的真實公開案例驗收。

### 公開社群單篇貼文

- [ ] 定義核心 MVP 的公開社群平台與各平台獨立解析器。
- [ ] 擷取無須登入即可讀取的公開單篇貼文文字、作者、日期與原始連結。
- [ ] 私人內容、登入限制、付費內容或非單篇貼文會明確失敗且不繞過限制。
- [ ] 以使用者核准的真實公開單篇貼文驗收。

### 內容管理與部署

- [ ] 支援本機編輯與重新產生摘要。
- [x] 支援下架與重新發布，並保留建立與更新時間。
- [ ] 實作 `evaluate-classifier`、`build-site` 與稍後獨立的 `deploy` 指令。
- [x] 在取得明確授權後設定 GitHub repository，並推送 `master`。
- [x] 建立 official GitHub Pages workflow，並完成本機 build、測試、base-path 連結與敏感資料 gate。
- [x] 完成真實 GitHub Pages deployment 與公開 smoke acceptance（<https://yamopeng0918.github.io/AI-Summary/>）。
- [x] 執行部署前建置與追蹤檔案、`site/dist` 敏感資料掃描。
- [ ] 驗證部署失敗時保留本機資料與可重試狀態。

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
