# AI Digest MVP 設計規格

## 1. 目標與範圍

AI Digest 是一套在本機執行的內容摘要與分類工具。使用者輸入公開網址後，系統擷取內容、產生繁體中文摘要、預測既有分類、保存結構化資料，並以 GitHub Pages 公開展示。

最新版 `提案企劃書_彭元懋.docx` 是本規格的需求基準。MVP 必須支援：

- 公開且可直接讀取的一般網頁。
- YouTube 公開影片，包含無可用字幕的影片。
- 無須登入即可讀取的公開社群單篇貼文。
- 繁體中文短摘要、3～5 個重點、分類、標籤、AI 編輯觀點及來源資料。
- 可量化評估且優於最大類基準的分類模型。
- GitHub Pages 摘要列表、詳情、搜尋、分類篩選及日期排序。

PDF／論文、圖片 OCR、標籤篩選、常駐後端、網站管理後台及帳號系統不屬於核心 MVP。PDF、OCR 與標籤篩選只在核心 MVP 穩定且時程允許時加入。

## 2. 技術方案

採用 Python 處理管線、Astro 靜態網站，以及 TF-IDF 搭配 Logistic Regression 的分類器。

此方案讓擷取、摘要、分類和保存留在適合資料處理與機器學習的 Python 環境；Astro 僅讀取已驗證的靜態 JSON，因此瀏覽器與 GitHub Pages 不會接觸 OpenAI 或其他本機憑證。

替代方案未採用的原因：

- 純 HTML／JavaScript 網站初期簡單，但列表、詳情、搜尋和建置資料會逐步難以維護。
- TypeScript 處理工具搭配獨立 Python 分類器會增加跨語言介面，對本次時程沒有足夠收益。

## 3. 系統架構與邊界

處理流程為：

```text
公開網址
   ↓
Python CLI
   ├─ 來源辨識
   ├─ 內容擷取
   ├─ OpenAI 結構化摘要
   ├─ 分類器預測
   └─ Schema 驗證與保存
            ↓
      data/summaries/*.json
            ↓
        Astro 靜態網站
   ├─ 摘要列表
   ├─ 摘要詳情
   ├─ 關鍵字搜尋
   ├─ 分類篩選
   └─ 日期排序
            ↓
       GitHub Pages
```

元件邊界如下：

- Python CLI 負責流程編排，不直接產生或操作網站畫面。
- 來源解析器只將外部來源轉成統一的擷取結果，不呼叫 OpenAI 或寫入摘要資料。
- 摘要服務接收乾淨文字並回傳固定結構，不負責擷取或保存。
- 分類器接收文字並回傳分類名稱，不修改摘要內容。
- 儲存層先驗證 Schema，再以獨立 JSON 檔案保存完整摘要。
- Astro 只讀取 `published` 摘要，不包含密鑰，也不發出 OpenAI 請求。
- 每種來源解析器獨立封裝；單一平台失效不得破壞其他來源流程。

第一個可交付里程碑只打通「公開網頁 → 摘要 JSON → 本機 Astro 網站」。YouTube、社群與部署在此基線通過後加入。

## 4. 摘要資料模型

每筆摘要保存為 `data/summaries/<id>.json`，格式如下：

```json
{
  "schemaVersion": 1,
  "id": "20260809-example-article",
  "canonicalUrl": "https://example.com/article",
  "sourceType": "web",
  "title": "文章標題",
  "author": null,
  "sourcePublishedAt": null,
  "createdAt": "2026-08-09T14:00:00+08:00",
  "updatedAt": "2026-08-09T14:00:00+08:00",
  "summary": "繁體中文短摘要",
  "keyPoints": ["重點一", "重點二", "重點三"],
  "category": "人工智慧",
  "tags": ["生成式 AI", "OpenAI"],
  "editorial": "AI 編輯觀點",
  "status": "published"
}
```

資料規則：

- `schemaVersion` 第一版固定為整數 `1`。
- `sourceType` 在完整 MVP 可為 `web`、`youtube` 或 `social`。
- `keyPoints` 必須有 3～5 個非空字串。
- `category` 必須存在於版本控制內的分類清單。
- `tags` 必須有 1～5 個非空字串；保存前移除首尾空白及不分大小寫的重複值。
- 所有系統產生時間使用包含時區的 ISO 8601 格式；第一版預設使用 `Asia/Taipei`。
- `status` 只能是 `published` 或 `archived`。下架只改為 `archived`，不刪除資料。
- 網站建置時忽略 `archived` 資料。
- URL 經過正規化後形成 `canonicalUrl`；查詢參數依來源規則保留或移除。
- 已存在相同 `canonicalUrl` 時，`add` 必須失敗；只有日後明確的更新操作可以覆寫內容。
- 任何必填欄位不合格時不得寫入新檔或覆寫既有檔案。

## 5. 分類模型與評估

第一版分類器採 TF-IDF 特徵搭配 Logistic Regression，初始分類限制為 4～6 個互斥主分類，每筆摘要只輸出一個 `category`。

人工標註資料以 CSV 保存，至少包含 `text` 與 `label`。訓練與測試採固定 random seed，並在各分類資料量允許時使用分層切分。評估輸出保存為 JSON，至少包含：

- 資料集版本或內容雜湊。
- 訓練與測試筆數。
- 各分類樣本數。
- Accuracy。
- Macro F1。
- 混淆矩陣及標籤順序。
- 最大類基準 Accuracy。
- 模型是否勝過基準。

MVP 驗收要求測試集 Accuracy 嚴格高於最大類基準。若標註資料不足或尚未達標，系統不得宣稱分類模型完成；其他管線可以使用明確標示為開發用途的暫時分類器繼續整合。

## 6. CLI 介面

第一版規劃以下命令：

```powershell
ai-digest add https://example.com/article
ai-digest list
ai-digest show 20260809-example-article
ai-digest archive 20260809-example-article
ai-digest publish 20260809-example-article
ai-digest evaluate-classifier
ai-digest build-site
```

操作規則：

- `add` 依序顯示來源辨識、擷取、摘要、分類、驗證及保存進度。
- `add` 成功時輸出摘要 ID 與檔案路徑；任一階段失敗時不留下不完整摘要。
- `list` 顯示 ID、標題、分類與發布狀態。
- `show` 顯示一筆摘要的完整結構化內容。
- `archive` 與 `publish` 只修改狀態與 `updatedAt`。
- `evaluate-classifier` 訓練並評估分類器，保存模型與 JSON 報告。
- `build-site` 執行網站資料驗證與靜態建置。
- 部署不隱藏在 `add` 中。完整 MVP 後期新增獨立 `deploy` 指令，以避免開發測試意外公開內容。

## 7. 錯誤模型與安全性

內部錯誤統一表示為：

```json
{
  "stage": "extract",
  "code": "CONTENT_UNAVAILABLE",
  "message": "無法取得可摘要的公開正文",
  "retryable": false
}
```

錯誤階段包含：

- `input`：網址不合法、不支援的來源或重複 URL。
- `extract`：來源無法讀取、需要登入或正文不足。
- `summarize`：OpenAI 請求失敗、限流或輸出不符合結構。
- `classify`：模型不存在、分類清單不一致或預測失敗。
- `save`：Schema 驗證或檔案寫入失敗。
- `deploy`：網站建置、Git 或 GitHub Pages 部署失敗。

失敗時不得建立看似成功的空摘要。可重試錯誤需清楚標記；不可讀、需登入、付費牆與反爬蟲來源不得嘗試繞過限制。

OpenAI API 金鑰、NotebookLM 驗證資料及 GitHub 憑證只保存在本機環境，不寫入摘要 JSON、前端資產、測試 fixture 或 Git。專案提供 `.env.example`，但不提供真實值。

## 8. 網站 MVP

Astro 網站包含：

- 首頁摘要卡片列表。
- 獨立摘要詳情頁。
- 標題、摘要與重點的關鍵字搜尋。
- 單一分類篩選。
- 最新及最舊排序。
- 分類、標籤、AI 編輯觀點、來源資料及原文連結。
- 載入成功但無資料、搜尋無結果與資料驗證失敗狀態。
- 手機及桌面基本響應式版面。

網站不包含登入、管理後台、瀏覽器端 AI 請求、常駐後端、複雜動畫或主題切換。標籤會顯示，但標籤篩選不是核心 MVP。

## 9. 測試策略

所有正式行為依測試驅動開發實作：先建立會因功能缺失而失敗的測試，確認失敗原因，再寫最小實作並重跑完整相關測試。

測試分層如下：

- 單元測試：URL 正規化、Schema 驗證、標籤清理、狀態修改及分類輸出。
- 契約測試：摘要服務回傳必須符合固定欄位、數量與型別。
- 擷取測試：使用版本控制內的本地 HTML fixture，不依賴外部網站。
- 整合測試：本地 HTML 經擷取、摘要服務替身、分類器替身後產生有效 JSON。
- 分類評估測試：固定小型資料集可重現指標與最大類基準。
- 網站測試：建置期間驗證資料，並測試列表、詳情、搜尋、分類篩選與排序。
- 真實來源驗收：獨立於日常測試執行，記錄測試日期、網址與結果，避免網路或網站變動造成一般測試不穩定。
- 安全檢查：掃描追蹤檔案與建置輸出，不得包含已知憑證格式或本機 `.env` 值。

## 10. 交付順序

1. 同步最新版企劃、初始化 Git 並建立專案骨架。
2. 建立資料模型、Schema、URL 正規化及本機儲存。
3. 完成公開網頁擷取與 OpenAI 結構化摘要。
4. 建立 Astro 網站並讀取範例摘要。
5. 建立人工標註格式、分類訓練及評估流程。
6. 串接公開網頁完整流程。
7. 加入 YouTube 有字幕與無字幕流程。
8. 加入可直接讀取的公開社群貼文。
9. 完成 GitHub Pages 部署、獨立 `deploy` 命令與安全檢查。
10. 視剩餘時間加入標籤篩選、PDF 或 OCR。

每一階段完成後都必須產生可獨立測試的成果，不以只有空目錄或未連線的介面視為完成。

## 11. 第一里程碑驗收標準

第一輪實作完成時必須同時符合：

- Python 自動測試全部通過且沒有警告或錯誤輸出。
- 本地 HTML fixture 能完成擷取、摘要資料轉換、分類及 JSON 保存。
- 至少一個真實公開網頁完成端到端處理。
- OpenAI 輸出不合格式時不會留下不完整資料。
- Astro 可完成正式建置，並顯示摘要列表與獨立詳情。
- 儲存庫、前端與建置輸出不包含 API 金鑰或其他憑證。
- `progress.md` 與 `todo.md` 已同步本規格的 MVP 範圍。
- 所有新增正式函式均有曾因功能缺失而失敗的測試。

GitHub 遠端儲存庫及 Pages 網址尚未提供，因此第一里程碑以本機 Git、可重現建置及本機網站為驗收範圍；遠端設定在部署階段完成。
