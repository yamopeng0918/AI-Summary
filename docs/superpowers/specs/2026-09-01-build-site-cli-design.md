# AI Digest `build-site` CLI 設計

## 1. 目的與範圍

新增本機命令：

```powershell
ai-digest build-site
```

此命令提供單一、可重現的 GitHub Pages 本機正式建置入口。成功代表 Astro 正式建置、Pages base-path 與 artifact 驗證，以及 Git 追蹤檔案和 `site/dist` 的敏感資訊掃描全部通過。

本功能只負責本機建置與驗證，不執行 `npm ci`、Git commit、push、GitHub Actions、公開網站 smoke test 或部署。`deploy` 必須在後續另行設計與核准。

## 2. 採用方案

採用獨立 Python 建置服務協調既有命令，而不在 CLI 內直接堆疊 subprocess 邏輯，也不以 Python 重寫 Astro 或 deployment verifier。

此方案沿用 `site/package.json` 的 `build:pages` 與 `scripts/verify_deployment.py` 作為既有真實來源，避免產生兩套不一致的建置或安全 gate，同時保留可注入 command runner 的單元測試邊界。

## 3. 架構與責任

新增 `src/ai_digest/site_build.py`，其中的 `SiteBuildService` 負責：

- 接收 repository root 與可替換的 command runner。
- 依平台選擇 `npm.cmd` 或 `npm`。
- 依序執行既有 Pages 建置和完整 deployment verifier。
- 將非零結束碼或命令啟動例外轉換為安全的 `DigestError`。
- 成功時回傳已解析的 `site/dist` 路徑。

CLI 只負責建立服務、輸出進度、輸出成功結果，以及以既有方式輸出結構化錯誤。服務不解析摘要、不修改 JSON、不建立 provider 或分類器，也不讀取 API 金鑰。

## 4. 固定命令與執行目錄

第一步在 `<repository>/site` 執行：

```text
Windows: npm.cmd run build:pages
其他平台: npm run build:pages
```

`build:pages` 保持既有責任：執行 Astro check、正式建置、OG 圖產生，以及 dist/base-path 驗證。

第二步在 repository root 使用目前 Python interpreter 執行：

```text
<python> scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
```

第二步再次驗證 `site/dist` 並額外掃描 Git 追蹤檔案。路徑與 `/AI-Summary/` 不提供 CLI override，避免使用者不慎略過本 repository 的固定部署契約。

命令不執行 `npm ci`，因此不會隱含下載依賴或執行未核准的 install scripts。若本機依賴尚未準備完成，命令必須明確失敗。

## 5. CLI 輸出契約

命令不接受額外參數。

成功時依序輸出下列 JSON Lines：

```json
{"stage":"deploy","step":"build"}
{"stage":"deploy","step":"verify"}
{"stage":"complete","path":"<resolved-repository>/site/dist"}
```

成功 exit code 為 `0`。實際 command runner 不擷取子程序輸出，讓 Astro 與 verifier 的正常診斷直接顯示於互動終端；CLI 自己的事件仍維持 JSON Lines。

## 6. 錯誤處理

任一步失敗立即停止，exit code 為 `1`，並使用既有 `DigestError.as_dict()` 格式輸出到 stderr。

建置失敗：

```json
{
  "stage": "deploy",
  "code": "SITE_BUILD_FAILED",
  "message": "site build command failed",
  "retryable": false
}
```

驗證失敗：

```json
{
  "stage": "deploy",
  "code": "SITE_BUILD_FAILED",
  "message": "site verification failed",
  "retryable": false
}
```

非零結束碼與命令啟動例外均映射到該步驟的固定安全訊息。結構化錯誤不得包含 subprocess stdout、stderr、原始例外文字、環境變數或憑證。若建置步驟失敗，不得執行 verifier。

## 7. TDD 測試設計

先新增 `tests/test_site_build.py` 並確認測試因尚無實作而失敗，覆蓋：

- Windows 使用 `npm.cmd`，其他平台使用 `npm`。
- 建置命令在 `site` 目錄執行。
- verifier 使用目前 Python interpreter，並在 repository root 執行。
- 兩個命令的參數與執行順序固定。
- 建置失敗後不執行 verifier。
- verifier 非零結束時回報驗證失敗。
- 命令、目錄或腳本無法啟動時轉成安全的 `DigestError`。
- 原始 stdout、stderr 與例外文字不會出現在結構化錯誤。
- 成功只回傳已解析的 `site/dist` 路徑。

再於 `tests/test_cli.py` 先新增失敗測試，覆蓋：

- `build-site` 命令存在且不接受額外參數。
- CLI 依序輸出 build、verify 與 complete 事件。
- 成功 exit code 為 `0`。
- 失敗輸出既有錯誤格式且 exit code 為 `1`。
- 建立或執行 `build-site` 不初始化摘要 provider、分類器或其他無關服務。

每組測試都必須先觀察預期失敗，再寫入使其通過的最小實作。

## 8. 實作後驗證

完成最小實作後依序執行：

1. `tests/test_site_build.py` 與相關 `tests/test_cli.py` focused tests。
2. 完整 Python `pytest`。
3. `site` 下的前端 `npm.cmd test`（非 Windows 使用 `npm test`）。
4. 實際執行 `ai-digest build-site`。
5. 確認 Astro 正式建置、依當下 `published` 資料產生的頁面與 OG artifacts、base path、tracked files 與 `site/dist` 敏感資訊掃描全部成功。
6. `git diff --check`。

最後更新 `README.md`、`progress.md` 與 `todo.md`。只有上述驗證實際通過，才可把 `build-site` 標記為完成；不得把尚未設計的 `deploy` 一併勾選。

## 9. 非目標

- 不安裝或更新 Node.js dependencies。
- 不新增可變更 site root、dist path 或 Pages base path 的選項。
- 不新增網路請求或付費 API 呼叫。
- 不修改、建立或重新產生摘要資料。
- 不執行 Git commit、push、PR 或遠端部署。
- 不擴張至 PDF、OCR、登入內容、私人內容、完整討論串或網站後台。
