# Gemini 摘要供應商設計

日期：2026-08-13

## 目標

讓 AI Digest 可透過明確的環境變數選擇 Gemini 或 OpenAI 作為文章摘要供應商，並將 Gemini 設為預設供應商。既有 OpenAI 功能必須維持相容。

## 設定介面

- `AI_DIGEST_PROVIDER` 接受 `gemini` 或 `openai`，未設定時使用 `gemini`。
- Gemini 使用 `GEMINI_API_KEY`，模型由 `GEMINI_MODEL` 指定；未設定模型時使用 `gemini-2.5-flash`。
- OpenAI 繼續使用 `OPENAI_API_KEY`，模型由 `OPENAI_MODEL` 指定；未設定模型時使用既有預設 `gpt-5-mini`。
- CLI 只檢查目前選定供應商所需的金鑰。
- 未知的 `AI_DIGEST_PROVIDER` 值回傳 `input / INVALID_PROVIDER`，不自動猜測或回退至其他供應商。
- 缺少所選供應商的金鑰時回傳 `input / MISSING_API_KEY`，訊息指出需要設定的環境變數。

## 架構

新增獨立的 `GeminiSummarizer`，並維持現有 `Summarizer` protocol。CLI 的 workflow 組裝層依 `AI_DIGEST_PROVIDER` 建立對應的 SDK client 與 summarizer：

1. `gemini`：使用 Google 官方 `google-genai` Python SDK及 `GeminiSummarizer`。
2. `openai`：沿用 OpenAI SDK及 `OpenAISummarizer`。

供應商選擇只存在於組裝層，文章擷取、分類、儲存與 Astro 呈現不感知供應商差異。此邊界讓兩個 adapter 可獨立測試，也避免把 Gemini 行為混入既有 OpenAI adapter。

## Gemini 請求與回應

`GeminiSummarizer` 將文章標題與正文送入 Gemini，沿用現有摘要指令與 `SummaryDraft` 欄位要求。請求使用：

- `response_mime_type="application/json"`
- 從 `SummaryDraft` 產生的 JSON Schema 作為 response schema

回應先解析為 JSON，再以 `SummaryDraft.model_validate` 驗證。只有驗證成功的資料可進入後續分類及儲存流程。

## 錯誤處理

Gemini adapter 將 SDK 例外及不合法回應映射至既有 `DigestError`：

- 逾時：`summarize / TIMEOUT`，可重試。
- 限流：`summarize / RATE_LIMITED`，可重試。
- 連線或暫時性伺服器錯誤：`summarize / REQUEST_FAILED`，可重試。
- 非暫時性 API 錯誤：`summarize / REQUEST_FAILED`，不可重試。
- 安全阻擋或拒絕：`summarize / REFUSAL`，不可重試。
- 空白、非 JSON 或不符合 `SummaryDraft` 的內容：`summarize / INVALID_RESPONSE`，不可重試。

對外錯誤訊息不得包含 API key、完整文章正文或來源 URL。

## 依賴與文件

- 在 Python runtime dependencies 新增官方 `google-genai` 套件，使用相容的上限避免未來 major version 自動升級。
- `.env.example` 加入 provider、Gemini 及 OpenAI 範例設定，不放真實秘密。
- README 說明預設 Gemini、兩種 provider 的設定方式，以及切換範例。
- `progress.md` 與 `todo.md` 在功能與驗收完成後同步更新。

## 測試策略

依 TDD 實作，先建立失敗測試再新增 production code：

1. Gemini adapter 成功取得並驗證結構化 `SummaryDraft`。
2. Gemini adapter 對逾時、限流、API 錯誤、拒絕及不合法回應的安全錯誤映射。
3. CLI 未設定 provider 時預設建立 Gemini workflow。
4. CLI 可明確選擇 OpenAI，維持原有模型預設及行為。
5. 未知 provider 與缺少對應 API key 時回傳正確錯誤。
6. 未使用 `add` 的本機命令在沒有任何 API key 時仍可執行。
7. 完整 Python 測試、前端測試及 Pages 建置維持通過。

## 真實端到端驗收

在 `GEMINI_API_KEY` 可用時，以一個可公開讀取的文章 URL 執行 `ai-digest add`，驗證：

1. 網頁擷取成功。
2. Gemini 回傳通過 `SummaryDraft` 驗證的摘要。
3. repository 寫入新的 published JSON。
4. Astro Pages 建置包含新摘要，且部署敏感資料掃描通過。

若本機沒有 `GEMINI_API_KEY`，自動測試與建置仍須完成；真實 API 驗收保持明確的 `UNVERIFIED` 狀態，不使用假結果冒充完成。

## 非目標

- 不移除 OpenAI 支援。
- 不在 Gemini 與 OpenAI 之間自動回退。
- 不變更摘要資料 Schema、分類器、擷取器或 Astro 頁面設計。
- 不在 repository、JSON 或建置產物中保存 API key。
