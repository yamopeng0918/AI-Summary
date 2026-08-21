# YouTube 核心來源設計

日期：2026-08-21
狀態：已核准，待撰寫實作計畫

## 1. 目標與範圍

本設計為 AI Digest MVP 新增公開 YouTube 單支影片來源，涵蓋有可用字幕與無可用字幕兩種情況。輸出沿用既有繁體中文摘要、分類、標籤、AI 編輯觀點與 JSON 儲存流程。

本階段只處理公開且無須登入即可取得的影片。不支援私人影片、會員限定影片、需要 Cookie 或年齡驗證的影片、正在直播或尚未開始的影片，也不加入播放清單批次匯入、帳號系統、常駐後端或繞過存取限制的能力。

單支影片預設最長兩小時。此限制可設定，但超過上限時必須在下載音訊前停止。

## 2. 核准方案

採用「字幕優先、音訊轉錄備援」：

1. 先取得公開影片中繼資料與字幕資訊。
2. 優先使用人工字幕，其次使用自動字幕。
3. 只有在沒有可用字幕時，才以 `yt-dlp` 下載公開音訊、用 FFmpeg 轉換及分段，再交給 OpenAI 語音轉文字 API。
4. 逐字稿完成後才交給既有 summarizer；來源解析器不得自行摘要、分類或保存資料。

此方案兼顧字幕影片的速度與成本，並滿足 MVP 必須支援無字幕影片的要求。所有影片一律轉錄會造成不必要的下載與 API 成本；同時取得字幕與轉錄再比較則增加 MVP 不需要的品質判定複雜度，兩者均不採用。

## 3. 架構與責任邊界

資料流如下：

```text
CLI URL
  -> SourceDetector
  -> ExtractorRouter
      |-- WebExtractor
      `-- YouTubeExtractor
            |-- MetadataProbe
            |-- CaptionExtractor
            `-- AudioTranscriber (無字幕時)
  -> Summarizer
  -> Classifier
  -> SchemaValidator
  -> JSONStorage
```

### 3.1 SourceDetector

- 先辨識 YouTube 網域，再判斷 URL 是否為支援的單支影片形式。
- 支援 `youtube.com/watch`、`youtu.be`、`youtube.com/shorts` 與 `youtube.com/embed`。
- YouTube 頻道頁、播放清單頁及缺少影片 ID 的網址回報 `UNSUPPORTED_YOUTUBE_URL`，不得退回一般網頁擷取。
- 非 YouTube 的其他公開 HTTP(S) URL 繼續交給 `WebExtractor`，不改變既有網頁行為。

### 3.2 ExtractorRouter

- workflow 改依賴共用 extractor 介面與路由，不再直接依賴 `WebExtractor`。
- 共用介面輸入 URL，輸出標準化擷取結果。
- 擷取結果明確包含 `source_type`，值為 `web` 或 `youtube`。
- workflow 儲存擷取結果提供的來源類型，不再固定寫入 `web`。

### 3.3 YouTubeExtractor

- 只負責影片中繼資料及可摘要文字。
- 先檢查公開狀態、直播狀態與影片長度，再嘗試字幕或媒體下載。
- 回傳標題、頻道名稱、發布時間、canonical URL 與文字。
- 不呼叫摘要器、分類器或儲存層。
- `MetadataProbe`、`CaptionExtractor`、程序執行器及 `AudioTranscriber` 必須可替換，以便使用本地 fixture 與 fake 完成測試。

### 3.4 Schema 與 canonical URL

- `SummaryRecord.source_type` 由目前的 `web` 擴充為 `web | youtube`。
- 對外 JSON 使用既有 `sourceType` 欄位，不新增另一套 YouTube 專用摘要格式。
- canonical URL 統一為 `https://www.youtube.com/watch?v=<video_id>`。
- 時間點、播放清單關聯與追蹤參數不進入 canonical URL。
- 同一影片的 `watch`、`youtu.be`、`shorts` 或 `embed` 網址會由既有重複來源保護拒絕重複建立。

## 4. 字幕選擇與正規化

字幕選擇順序為：

1. 人工繁體中文字幕。
2. 人工原始語言字幕。
3. 其他可用人工字幕。
4. 自動繁體中文字幕。
5. 自動原始語言字幕。
6. 其他可用自動字幕。
7. 無可用字幕時進入音訊轉錄。

字幕保留來源語言，不在擷取階段強制翻譯；既有 summarizer 負責輸出繁體中文摘要。字幕正規化會移除時間碼、格式標記與連續重複片段，但保持內容原有順序。正規化後文字不足時回報錯誤，不建立空白或看似成功的摘要。

## 5. 無字幕音訊轉錄

1. 中繼資料檢查通過後，`yt-dlp` 只下載公開可取得的最佳音訊。
2. 不傳入 Cookie、登入資料、代理伺服器或繞過限制參數。
3. FFmpeg 將音訊轉為適合語音辨識的單聲道格式。
4. 音訊依可設定的時間與檔案大小上限切段。
5. 各段依序交給可替換的 OpenAI transcription client，預設模型為 `gpt-transcribe`。
6. 分段結果按原順序合併；任一段失敗時整次擷取失敗，部分逐字稿不得進入摘要流程。

OpenAI 官方文件說明 `gpt-transcribe` 支援已完成音訊檔及串流檔案的轉錄，並支援多語言提示；實際費率、模型可用性與帳戶限額以執行時官方設定為準。

## 6. 設定與依賴

- `AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS`：預設 `7200`。
- `AI_DIGEST_TRANSCRIPTION_MODEL`：預設 `gpt-transcribe`。
- `AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS`：使用安全預設值，並允許本機調整。
- `OPENAI_API_KEY`：只有影片確實需要音訊轉錄時才檢查。
- `yt-dlp` 與 FFmpeg：預設從系統 `PATH` 尋找。

即使摘要 provider 是 Gemini，有字幕影片也不需要 OpenAI 金鑰。無字幕影片才延遲建立 transcription client；缺少金鑰時不得開始音訊下載。程式不得接受任意 shell 命令作為工具設定，也不提供 Cookie、登入或代理參數。

## 7. 暫存檔與安全

- 每次音訊備援使用獨立暫存目錄。
- 成功、失敗或中斷後都必須清除下載音訊、轉換檔與字幕暫存檔。
- 音訊與字幕檔不得寫入 repository、摘要 JSON、前端資產或建置輸出。
- API 金鑰只從本機環境讀取。
- 對外錯誤不得包含金鑰、Cookie、完整 URL、暫存路徑、原始逐字稿，或 `yt-dlp`、FFmpeg、OpenAI SDK 的原始 stderr／例外文字。
- 不得嘗試繞過登入、會員、地區、年齡或其他存取限制。

## 8. 錯誤模型

沿用 `DigestError(stage, code, message, retryable)`。YouTube 擷取與轉錄都屬於 `extract` 階段。

| 代碼 | 情況 | retryable |
|---|---|---:|
| `UNSUPPORTED_YOUTUBE_URL` | YouTube URL 不是支援的單支影片形式 | `false` |
| `CONTENT_UNAVAILABLE` | 私人、會員限定、已刪除、地區限制或其他不可公開讀取狀態 | `false` |
| `LOGIN_REQUIRED` | 需要登入、Cookie 或年齡驗證 | `false` |
| `LIVE_STREAM_UNSUPPORTED` | 正在直播或尚未開始 | `false` |
| `VIDEO_TOO_LONG` | 超過設定的影片長度上限 | `false` |
| `MEDIA_TOOL_MISSING` | 找不到 `yt-dlp` 或 FFmpeg | `false` |
| `MEDIA_DOWNLOAD_FAILED` | 暫時性媒體下載失敗 | `true` |
| `TRANSCRIPTION_TIMEOUT` | OpenAI 轉錄逾時 | `true` |
| `TRANSCRIPTION_RATE_LIMITED` | OpenAI 轉錄遭限流 | `true` |
| `TRANSCRIPTION_FAILED` | 其他轉錄錯誤 | 依底層錯誤類型判斷 |
| `INSUFFICIENT_TEXT` | 字幕或完整轉錄仍不足以摘要 | `false` |

無字幕且缺少 `OPENAI_API_KEY` 時沿用輸入階段的 `MISSING_API_KEY` 安全錯誤。所有訊息只提供安全且可採取的下一步，不轉送第三方工具的原始錯誤內容。

## 9. TDD 實作順序

所有行為變更遵循先失敗測試、最小實作、相關測試、完整測試的順序。

### 9.1 來源辨識與 canonical URL

- 支援四種核准 URL 形式。
- 拒絕頻道、播放清單與無影片 ID 網址。
- 驗證查詢參數不影響 canonical URL。
- 驗證同一影片的多種 URL 形式會觸發重複來源保護。

### 9.2 共用介面與路由

- 驗證既有網頁來源行為不變。
- 驗證 workflow 儲存正確的 `web` 或 `youtube`。
- 驗證非 YouTube URL 不會呼叫 YouTube 工具。

### 9.3 中繼資料與限制

- 驗證公開影片成功。
- 驗證私人、需登入、直播中與超時長影片的錯誤映射。
- 驗證錯誤不洩漏原始工具輸出、URL 或暫存路徑。

### 9.4 字幕路徑

- 驗證人工字幕優先於自動字幕。
- 驗證語言排序、格式清理、連續重複移除與文字不足。
- 驗證有可用字幕時絕不下載音訊或呼叫 OpenAI。

### 9.5 音訊轉錄路徑

- 驗證下載、轉換、切段、依序轉錄與合併。
- 驗證任一分段失敗時不回傳部分結果。
- 驗證缺金鑰、工具缺失、限流、逾時與下載失敗。
- 驗證每個成功、失敗及中斷路徑都清理暫存資料。

### 9.6 CLI、Schema 與端到端

- 驗證 `sourceType: youtube` 通過 Python Schema 與 Astro content collection。
- 使用本地 fixture、fake subprocess runner 與 fake OpenAI client 完成端到端流程。
- 日常測試不得依賴外部網路、真實影片或付費 API。

## 10. 驗收條件

- 相關 Python 測試與完整 `pytest` 通過。
- 前端測試及 Astro 正式建置通過。
- 所有範例與既有摘要 JSON 通過 Schema 驗證。
- `git diff --check` 通過。
- 追蹤檔案與建置輸出不含金鑰、Cookie、音訊、字幕暫存檔或敏感命令輸出。
- 以一支短的公開有字幕影片及一支短的公開無字幕影片完成手動整合驗證。
- 若外部工具、API 金鑰或網路使手動驗證無法執行，必須明確記錄未驗證項目與原因，不得推測成功。
- 完成可交付單元後同步更新 `progress.md`、`todo.md`、`.env.example` 與適用操作文件；只有實際通過驗證的項目才標記完成。

## 11. 非目標

- 播放清單或頻道批次匯入。
- 私人、會員、付費、需登入或需 Cookie 的影片。
- 直播錄製或直播中摘要。
- 常駐下載服務、任務佇列或網站管理後台。
- 本機 Whisper 模型與 GPU 管理。
- 同時執行字幕及音訊轉錄後進行品質比較。
- 保存完整字幕、逐字稿或音訊供前端下載。

## 12. 參考資料

- 主要 MVP 設計：`docs/superpowers/specs/2026-08-09-ai-digest-mvp-design.md`
- OpenAI GPT Transcribe：<https://developers.openai.com/api/docs/models/gpt-transcribe>
