# AI Digest 本機編輯與重新產生摘要設計

## 目標

新增兩個本機 CLI 操作：使用外部文字編輯器安全修改既有摘要，以及從既有記錄的公開來源重新擷取、摘要與分類。兩者都更新原 JSON，不建立重複記錄，並在任何失敗下保留原資料。

## 範圍

本功能包含：

- `ai-digest edit <record-id>`：在外部文字編輯器中編輯既有摘要 JSON。
- `ai-digest regenerate <record-id>`：重新擷取來源、呼叫目前選定的摘要 provider、重新分類並覆寫既有摘要。
- 儲存層的驗證後原子覆寫能力。
- CLI、workflow、editor runner 與 repository 的自動化測試及操作文件。

本功能不包含網站管理後台、瀏覽器內編輯、版本歷史、多人協作、批次重新產生、復原介面或自動部署。

## 核准方案

採用專用更新流程：`EditSummaryWorkflow` 與 `RegenerateSummaryWorkflow` 分別負責編輯與重新產生的協調，`SummaryRepository` 負責 Schema 驗證後的原子覆寫。既有 `AddArticleWorkflow` 保持只建立新記錄，避免建立與更新規則互相糾纏。

## 公開 CLI

```powershell
ai-digest edit <record-id>
ai-digest regenerate <record-id>
```

兩個指令成功時都輸出 ASCII-safe JSON：

```json
{"stage":"complete","id":"<record-id>","path":"data/summaries/<record-id>.json"}
```

`edit` 不需要 provider 金鑰。`regenerate` 使用既有 `AI_DIGEST_PROVIDER` 選擇規則，只要求所選 provider 的金鑰；執行指令即代表同意該次付費摘要呼叫，不增加互動式確認提示。

## 編輯流程

1. `EditSummaryWorkflow` 由 repository 載入指定記錄。
2. workflow 將完整、格式化、UTF-8 JSON 寫入系統暫存檔。
3. editor runner 依序選擇 `VISUAL`、`EDITOR`；兩者皆未設定時，Windows 使用 `notepad.exe`，其他平台回報設定錯誤。
4. editor runner 以 `shlex.split()` 解析環境變數中的命令，將暫存檔路徑附加為最後一個參數，再以 `subprocess`、`shell=False` 等待編輯器結束。含空白的執行檔路徑必須在環境變數中加引號；需要等待的編輯器可設定為例如 `code --wait`。
5. 編輯器正常結束後，workflow 讀取並解析暫存 JSON，透過 `SummaryRecord` 執行完整 Schema 驗證。
6. 下列系統欄位必須與原記錄完全相同：`schemaVersion`、`id`、`canonicalUrl`、`sourceType`、`createdAt`。
7. 使用者可修改 `title`、`author`、`sourcePublishedAt`、`summary`、`keyPoints`、`category`、`tags`、`editorial`、`status`。
8. workflow 忽略使用者輸入的 `updatedAt` 值，固定以注入的 Asia/Taipei aware clock 設定新值。
9. repository 驗證後原子覆寫原記錄。
10. 成功或失敗都清理暫存檔。

若使用者未修改內容，流程仍視為一次成功編輯並更新 `updatedAt`；本設計不增加「無變更」的特殊狀態。

## 重新產生流程

`RegenerateSummaryWorkflow` 使用既有 extractor、summarizer、classifier 與 repository 邊界，依序執行：

```text
input → extract → summarize → classify → validate → save
```

具體規則：

1. `input` 載入既有記錄，以其 `canonicalUrl` 作為重新擷取輸入；目標記錄本身不構成重複 URL。
2. `extract` 使用現有來源 router。若解析器回傳的新 canonical URL 與另一筆記錄衝突，於呼叫付費摘要服務前回報 `DUPLICATE_URL`。
3. `summarize` 使用目前選定 provider 產生新的 summary、key points、tags 與 editorial。
4. `classify` 使用新來源標題、新摘要與新重點重新執行正式分類器，並維持既有分類集合驗證。
5. `validate` 建立新的 `SummaryRecord`。
6. 新記錄保留原本的 `id`、`createdAt`、`status`；採用新擷取結果的 `canonicalUrl`、`sourceType`、`title`、`author`、`sourcePublishedAt`，以及新的摘要、重點、分類、標籤與 AI 編輯觀點；`schemaVersion` 維持 `1`，`updatedAt` 使用注入 clock。
7. `save` 由 repository 原子覆寫原 JSON。

任何階段失敗時，不修改既有 JSON。

## 儲存層契約

`SummaryRepository` 新增：

```python
replace(record_id: str, updated_record: SummaryRecord) -> Path
```

此操作必須：

- 確認目標記錄存在，否則回報 `save / RECORD_NOT_FOUND`。
- 確認 `updated_record.id == record_id`，否則回報 `save / INVALID_RECORD`。
- 以 `SummaryRecord` 驗證待寫內容。
- 確認待寫 canonical URL 不與目標以外的記錄重複，否則回報 `save / DUPLICATE_URL`。
- 使用既有 temporary file、flush、`os.fsync` 與 `os.replace` 原子寫入。
- 寫入錯誤時清理 temporary file，回報 `save / WRITE_FAILED`，並保留原檔。

來源解析器不得寫入資料；摘要器不得擷取、分類或保存；分類器只接收文字並回傳分類。這些既有架構界線不變。

## 錯誤契約

所有 CLI 錯誤維持既有 ASCII-safe 結構：

```json
{"stage":"...","code":"...","message":"...","retryable":false}
```

新增或沿用的錯誤如下：

| 情況 | stage | code | retryable |
|---|---|---|---|
| 找不到記錄 | `save` | `RECORD_NOT_FOUND` | `false` |
| 非 Windows 且未設定編輯器 | `input` | `EDITOR_NOT_CONFIGURED` | `false` |
| 編輯器命令無法解析、無法啟動或非零結束 | `input` | `EDITOR_FAILED` | `false` |
| 編輯結果不是有效 UTF-8 JSON 或不符合 Schema | `save` | `INVALID_RECORD` | `false` |
| 受保護欄位遭修改 | `save` | `PROTECTED_FIELD_CHANGED` | `false` |
| canonical URL 與另一筆記錄衝突 | `input`（workflow 預檢）或 `save`（repository 最終防線） | `DUPLICATE_URL` | `false` |
| 原子寫入失敗 | `save` | `WRITE_FAILED` | `true` |

擷取、摘要、分類與 provider 設定錯誤沿用既有階段、代碼與安全訊息，不輸出金鑰、Cookie、暫存內容或外部服務敏感資料。

## 元件與依賴注入

- `EditorRunner`：只負責選擇與執行編輯器，不解析或保存摘要。
- `EditSummaryWorkflow`：協調載入、暫存 JSON、編輯、驗證、欄位保護、時間更新與 repository 覆寫。
- `RegenerateSummaryWorkflow`：協調重新擷取、衝突預檢、摘要、分類、驗證與覆寫。
- `SummaryRepository.replace()`：唯一正式覆寫邊界。
- CLI factory 注入 workflow factory、repository 與 clock，使測試不需真實編輯器、網路或付費 API。

## 測試與驗收

所有行為變更採 TDD，先確認最小測試因缺少行為而失敗，再加入最小實作。

### Repository

- 成功覆寫有效記錄。
- 找不到記錄。
- record ID 與參數不一致。
- canonical URL 與其他記錄重複。
- 寫入失敗不破壞原資料並清理 temporary file。

### 編輯流程

- 可修改所有核准內容欄位。
- 任一受保護欄位變更時拒絕保存。
- 無效 UTF-8、JSON 或 Schema 時拒絕保存。
- `updatedAt` 由 clock 設定。
- `VISUAL` 優先於 `EDITOR`。
- Windows 未設定環境變數時使用 Notepad；其他平台回報 `EDITOR_NOT_CONFIGURED`。
- 編輯器啟動失敗或非零結束時回報 `EDITOR_FAILED`。
- subprocess 使用參數陣列與 `shell=False`。
- 成功與所有錯誤路徑都清理暫存檔。

### 重新產生流程

- 進度階段順序正確。
- 保留 `id`、`createdAt`、`status`。
- 更新來源欄位、摘要欄位、分類與 `updatedAt`。
- resolved canonical URL 與其他記錄衝突時在 summarize 前停止。
- 任一遠端、分類、驗證或保存失敗都不覆寫原記錄。

### CLI 與完整驗證

- `edit` 與 `regenerate` 指令成功事件與結構化錯誤。
- `edit` 在沒有 provider key 時可用。
- `regenerate` 只建立目前所選 provider 的依賴。
- 執行相關 pytest 與完整 Python suite。
- 執行所有已保存摘要的 Schema 驗證、`scripts/verify_deployment.py --tracked` 與 `git diff --check`。

外部編輯器、網路與付費 API 不成為日常測試條件；測試使用暫存檔、fixture 與注入替身。

## 文件與進度

完成後更新 README 的 Windows PowerShell 範例、編輯器設定與付費重新產生說明；同步更新 `progress.md` 與 `todo.md`。未完成遠端部署前不宣稱 GitHub Pages 已更新，本功能本身也不自動 push 或部署。
