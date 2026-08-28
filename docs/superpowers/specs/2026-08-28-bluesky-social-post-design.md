# AI Digest Bluesky 公開單篇貼文擷取設計

日期：2026-08-28
狀態：已核准

## 目標

為 AI Digest MVP 增加 Bluesky 公開單篇貼文來源。使用者可提交一個無須登入即可讀取的官方 Bluesky 貼文網址，系統擷取可用文字後，沿用既有摘要、分類、Schema 驗證、JSON 保存與 Astro 展示流程。

本功能只支援貼文本身，不擴展成討論串、引用貼文或外部連結全文擷取器。

## 核准範圍

只接受下列官方網址格式：

```text
https://bsky.app/profile/<handle-or-did>/post/<post-id>
```

其中 `<handle-or-did>` 可為 Bluesky handle 或 DID。URL 的 query string 與 fragment 在本地解析階段移除。

本期不支援：

- Bluesky 個人檔案、搜尋、feed、starter pack 或其他頁面。
- 回覆貼文。
- 引用貼文內容與整個回覆串。
- 私人、受限或必須登入才能讀取的內容。
- 其他社群平台。
- 圖片下載、OCR、視覺辨識或自動產生圖片描述。
- 外部連結正文擷取。

## 架構與元件

新增獨立的 `BlueskyExtractor`，與一般網頁及 YouTube 擷取器隔離。它只負責 Bluesky 來源解析與內容擷取，不呼叫摘要服務、不分類，也不寫入摘要資料。

`source_urls` 負責在本地辨識核准的 Bluesky URL 形狀、驗證必要 path segment，並移除 query string 與 fragment；此階段不呼叫網路。

`ExtractorRouter` 依序辨識 YouTube、Bluesky，再回退至一般網頁擷取器。Bluesky 平台失效不得影響 YouTube 或一般網頁來源。

`BlueskyExtractor` 使用固定的公開 Bluesky AppView API 主機，不解析 `bsky.app` HTML，也不引入 Bluesky SDK：

1. 當輸入為 handle 時，透過公開 identity resolve API 解析 DID；輸入已是 DID 時不需解析。
2. 以 `at://<did>/app.bsky.feed.post/<post-id>` 取得單篇貼文。
3. 驗證貼文作者 DID、record 與必要欄位。
4. 將貼文資料轉成既有共用 `ExtractedArticle`，並設定 `sourceType` 為 `social`。

摘要服務、分類器、Schema 與儲存層維持既有責任，不加入 Bluesky 特例。

## Canonical URL 與重複判定

最終 `canonicalUrl` 一律使用作者 DID：

```text
https://bsky.app/profile/<did>/post/<post-id>
```

如此可讓 handle 改名、handle URL 與 DID URL 都映射到相同來源。儲存層沿用既有規則，對相同 `canonicalUrl` 預設拒絕重複建立。

擷取器不得僅信任輸入 URL 的身分。API 回傳貼文的作者 DID 必須與解析後 DID 一致；不一致視為無效來源回應。

## 內容映射

Bluesky 貼文映射至 `ExtractedArticle`：

| 欄位 | 來源與規則 |
|---|---|
| `title` | `<顯示名稱>（@handle）的 Bluesky 貼文` |
| `author` | 作者顯示名稱；沒有顯示名稱時使用 handle |
| `publishedAt` | 貼文建立時間，保留含時區的 ISO 8601 格式 |
| `canonicalUrl` | DID 形式的官方 `bsky.app` 貼文網址 |
| `sourceType` | `social` |
| `content` | 依序組合貼文文字、圖片 alt text、外部連結卡片標題 |

內容組合遵守下列規則：

- 保留原文中的 hashtags、mentions 與網址。
- 圖片只採用作者提供的非空白 alt text，不下載圖片，也不自行補寫描述。
- 外部連結只採用 Bluesky embed 中已提供的非空白標題，不請求該外部網址。
- 不納入引用貼文的文字、作者或附件。
- 不展開父貼文、子回覆或討論串。
- 各段內容以清楚且固定的文字標記分隔，避免摘要器把 alt text 或連結標題誤認為貼文正文。
- 同一段完全相同的非空白補充文字只納入一次。

貼文正文為空時，只要至少存在一筆圖片 alt text 或外部連結標題，仍可進入摘要流程。三者皆無可用文字時，擷取失敗且不得保存摘要。

## 回覆貼文判定

若貼文 record 具有有效的 reply reference，該貼文視為回覆貼文並以 `REPLY_POST_NOT_SUPPORTED` 拒絕。即使該回覆本身可以公開讀取，也不進入摘要流程。

引用貼文不是回覆貼文，但只摘要目前貼文自己的文字及核准的附件文字，不展開被引用內容。

## 錯誤處理

所有錯誤沿用既有結構：

```json
{
  "stage": "extract",
  "code": "...",
  "message": "...",
  "retryable": false
}
```

| 代碼 | 情況 | `retryable` |
|---|---|---|
| `INVALID_URL` | 非核准的 Bluesky 單篇貼文 URL | `false` |
| `REPLY_POST_NOT_SUPPORTED` | 目標 record 是回覆貼文 | `false` |
| `POST_NOT_FOUND` | 貼文不存在、已刪除或 AppView 查無貼文 | `false` |
| `AUTHOR_NOT_FOUND` | handle 無法解析成 DID | `false` |
| `NO_EXTRACTABLE_CONTENT` | 正文、圖片 alt text 與外部連結標題皆空 | `false` |
| `SOURCE_ACCESS_DENIED` | 內容需登入、受到限制或不是公開內容 | `false` |
| `UPSTREAM_UNAVAILABLE` | 逾時、HTTP 429 或 Bluesky 伺服器錯誤 | `true` |
| `INVALID_SOURCE_RESPONSE` | API 回應缺少必要欄位、型別錯誤或身分不一致 | `false` |

擷取器不執行長時間或無限重試。是否重新執行由既有 CLI 流程及錯誤的 `retryable` 值決定。擷取失敗時不得建立空白、猜測或看似成功的摘要。

## 安全與外部服務限制

- 只連線至程式內固定的 Bluesky 公開 AppView API 主機，不接受 URL、回應內容或設定檔指定替代 API endpoint。
- 不使用登入憑證、Cookie、App Password、使用者 Token 或其他 Bluesky 私密資料。
- 不繞過封鎖、登入、內容警告、付費或其他存取控制。
- 不請求 embed 內的外部連結或圖片 URL，避免 SSRF 與不必要的第三方連線。
- 日誌與錯誤訊息不輸出完整 API 回應；只保留診斷所需且已清理的公開識別資訊。
- 日常測試不得依賴外部網路或付費 API。

## TDD 與自動化測試

實作依 TDD 進行：先加入最小失敗測試，再撰寫最小實作並重跑相關及完整測試。Bluesky API 透過明確介面替換，測試使用本地 fixture。

### URL 與路由

- 接受核准的 handle 與 DID 貼文網址。
- 移除 query string 與 fragment。
- 拒絕非 `bsky.app`、非 `/profile/.../post/...`、缺少 handle/DID 或 post ID，以及額外 path segment。
- Bluesky URL 交由 `BlueskyExtractor`，既有 YouTube 與一般網頁路由不變。

### API 與資料轉換

- handle 正確解析為 DID；DID 輸入不重複解析。
- 正確擷取正文、作者、時間、圖片 alt text 與外部連結標題。
- 正確產生 DID 形式 `canonicalUrl`。
- 驗證解析 DID 與貼文作者 DID 一致。
- 不納入引用貼文、回覆串或外部頁面正文。
- 覆蓋純文字、僅 alt text、僅外部連結標題與混合內容。
- 拒絕回覆貼文與完全沒有可用文字的貼文。

### 錯誤與安全

- 覆蓋不存在、受限、429、逾時、伺服器錯誤與異常 API 回應。
- 驗證每種錯誤的 `stage`、`code` 與 `retryable`。
- 驗證不跟隨 embed 外部 URL、不傳送憑證、不接受替代 AppView 主機。
- 擷取失敗後不寫入摘要記錄。

### 整合與回歸

- CLI 可新增一筆 fixture Bluesky 摘要，並可由 `list` 與 `show` 查詢。
- 同一貼文的 handle URL 與 DID URL 視為相同 canonical URL，拒絕重複建立。
- 驗證所有已保存資料符合 Schema。
- 完整 Python 測試集通過。
- 相關前端測試、Astro check 與正式 Pages build 通過。

## 遠端驗收

使用一篇無須登入、非回覆且內容穩定的公開 Bluesky 貼文進行一次端到端驗收：

1. CLI 成功擷取、產生繁體中文摘要、分類、驗證並保存。
2. JSON 的 `sourceType` 為 `social`，且 `canonicalUrl` 使用 DID。
3. GitHub Pages 列表、搜尋與詳情頁正常顯示該摘要。
4. 詳情頁的原始來源連結可前往官方 Bluesky 貼文。
5. 只執行一次必要的付費摘要呼叫；自動化測試不呼叫付費 API。

若外部服務、憑證或公開測試貼文狀態導致無法完成驗收，必須將該項標記為未驗證並記錄原因，不得推測成功。

## 完成條件

- 上述 URL、路由、內容映射、錯誤與安全測試均通過。
- 完整 Python 與前端驗證保持通過。
- Bluesky 擷取不改變既有摘要、分類、Schema 或儲存責任邊界。
- `progress.md` 與 `todo.md` 只記錄實際完成且已驗證的結果。
- 遠端驗收結果有明確證據；未驗證項目保持未完成狀態。
