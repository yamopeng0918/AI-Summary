# AI Digest `deploy` CLI 設計

## 1. 目的與範圍

新增無參數命令：

```powershell
ai-digest deploy
```

此命令只部署目前 repository 中已提交的 `master`。它不建立或修改摘要、不自動提交檔案，也不初始化摘要 provider 或分類器。成功代表本機正式建置與敏感資料 gates 通過、必要的 fast-forward push 已完成、相同 HEAD 的 GitHub Pages workflow 成功，且公開網站 smoke 驗證通過。

未追蹤檔案不阻擋部署，也永遠不會被加入、提交或推送；任何 tracked file 的未提交變更都會使 preflight 失敗。

## 2. 採用方案

新增獨立 `DeployService`，重用現有 `SiteBuildService`，並以可注入的 Git command runner、GitHub workflow client、sleep callback 與 public smoke runner 保持所有外部作用可測試。CLI 的 deploy 組合為 Git、npm／Astro build、verifier 與 public smoke 共用同一個捕捉型 runner；獨立的 `build-site` 組合則維持既有即時診斷輸出。

不擴充 `SummaryPublisher`：該服務負責單篇摘要的建立與發布，若同時承擔一般 repository 部署，會把部署錯誤地綁定到摘要 provider 與內容建立流程。

CLI 只建立服務、輸出 JSON Lines 進度與完成結果，並沿用既有 `DigestError` 錯誤輸出；Git、HTTP、輪詢與 smoke 邏輯不直接堆疊在 Typer command 中。

## 3. 固定部署流程

`DeployService.run()` 依序執行：

1. 確認目前目錄是 repository root。
2. 確認目前分支是 `master`。
3. 確認 tracked files 沒有 staged 或 unstaged 變更；忽略 untracked files。
4. 執行 `git fetch origin master`。
5. 執行 `git rev-list --left-right --count master...origin/master`，將第一個數字視為 `local_only`、第二個數字視為 `remote_only`：
   - `local_only == 0` 且 `remote_only == 0`：已同步，後續不 push。
   - `local_only > 0` 且 `remote_only == 0`：只在本機超前，允許完成本機 gates 後 push 全部已提交 commits。
   - `remote_only > 0`：本機落後或雙方分歧，fail closed，不 build、不 push。
6. 執行既有 `SiteBuildService`，完成 `build:pages` 與 tracked／`site/dist` verifier。
7. 若本機超前，執行固定命令 `git push origin master`；若已同步則略過 push。
8. 取得目前 HEAD SHA，查詢名稱為 `Deploy to GitHub Pages` 且 `head_sha` 相同的 workflow：
   - 已成功：直接使用該 run。
   - queued 或 in progress：有限次輪詢。
   - 失敗、取消或逾時：回報錯誤。
9. 執行既有 `scripts/smoke_pages.py`，確認公開 Pages 網站可讀取。
10. 回傳 commit SHA、workflow URL 與固定公開站 URL。

若本機與遠端已同步，命令不透過 `workflow_dispatch` 重複部署；它只驗證相同 commit 已存在的成功 workflow 與公開網站。

## 4. Git 與遠端安全邊界

- 只允許 `master`，remote 固定為 `origin`。
- 只允許一般 `git push origin master`；禁止 force push。
- 不執行 `git add`、`git commit`、`git reset`、checkout、pull、rebase 或 history rewrite。
- fetch 或 push 的非零結束碼立即停止。
- build 未通過前不得 push。
- push 已成功但 workflow 或公開 smoke 失敗時，不回滾 commit、不刪除資料，也不把部署標記為完成。
- GitHub workflow 狀態使用公開 API 查詢，不讀取或要求 GitHub Token。
- 命令不讀取 provider 金鑰，也不需要付費 API。

## 5. CLI 輸出契約

正常執行依序輸出 JSON Lines：

```json
{"stage":"deploy","step":"preflight"}
{"stage":"deploy","step":"build"}
{"stage":"deploy","step":"verify"}
{"stage":"deploy","step":"push","status":"pushed"}
{"stage":"deploy","step":"workflow"}
{"stage":"deploy","step":"public"}
{"stage":"complete","commit":"<sha>","workflow":"<url>","site":"https://yamopeng0918.github.io/AI-Summary/"}
```

若 HEAD 已與 `origin/master` 同步，push 事件為：

```json
{"stage":"deploy","step":"push","status":"unchanged"}
```

`SiteBuildService` 產生的 `build` 與 `verify` 事件透過同一個 progress callback 轉送，不重複輸出。`deploy` 的 stdout 與 stderr 只允許上述 JSON Lines：所有 Git、npm／Astro、verifier 與 public smoke 子程序輸出都必須捕捉且不得轉送；成功進度與完成結果寫到 stdout，失敗只在 stderr 寫入結構化 `DigestError`。成功 exit code 為 `0`，失敗 exit code 為 `1`。

這項限制只適用於 `deploy`。獨立執行 `build-site` 時保留既有的 npm／Astro／verifier 即時診斷，方便人工疑難排解。

## 6. 錯誤契約

所有錯誤沿用 `DigestError.as_dict()`：

| code | 適用情況 | retryable |
|---|---|---|
| `DEPLOY_PREFLIGHT_FAILED` | 非 root、非 `master`、tracked files 不乾淨、本機落後或分歧 | `false` |
| `SITE_BUILD_FAILED` | 沿用既有 build 或 verifier 失敗 | `false` |
| `DEPLOY_PUSH_FAILED` | fetch 或 push 失敗 | `false` |
| `DEPLOY_WORKFLOW_FAILED` | workflow 明確失敗或取消 | `false` |
| `DEPLOY_WORKFLOW_FAILED` | workflow 查詢暫時失敗或輪詢逾時 | `true` |
| `DEPLOY_PUBLIC_FAILED` | 公開網站請求或 smoke 驗證失敗 | `true` |

錯誤的 `stage` 均為 `deploy`。每個 code 使用固定、簡短且不含外部內容的 message。結構化錯誤不得包含 subprocess stdout／stderr、HTTP response body、原始例外文字、環境變數、憑證或敏感本機路徑。

## 7. TDD 測試設計

先新增最小失敗測試，實作最小行為，再逐項擴充。服務測試至少覆蓋：

- repository root、`master` 與 tracked-clean preflight。
- untracked files 不阻擋部署。
- 同步狀態不 push，直接查驗相同 HEAD 的既有 workflow。
- 僅本機超前時，完整 gates 通過後 push 全部 commits。
- 本機落後或分歧時 fail closed。
- build 失敗時不 push。
- push 失敗時不查 workflow。
- workflow 已成功、queued／in-progress 輪詢、明確失敗、查詢錯誤與逾時。
- 公開 smoke 成功與失敗。
- 所有錯誤訊息與 retryable 值符合契約，且不洩漏外部輸出或例外內容。

CLI 測試至少覆蓋：

- `deploy` 存在且不接受額外參數。
- 完整事件順序，以及 `pushed`／`unchanged` 兩種 push 狀態。
- 即使 build 或 verifier 產生 stdout／stderr 噪音，`deploy` 的兩個 stream 仍只包含合法 JSON Lines。
- 成功與失敗 exit code。
- 不初始化 provider、分類器或摘要 repository。
- `build-site` 既有即時診斷行為不受影響。

所有自動化測試必須使用 fake runner、fixture 或注入 client，不依賴真實網路、GitHub、付費 API 或真實 push。

## 8. 完成驗證

實作完成後依序執行：

1. deploy service 與 CLI focused tests。
2. 完整 Python suite。
3. 完整 Vitest。
4. 實際執行 `ai-digest build-site`。
5. tracked／`site/dist` deployment verifier 與 `git diff --check`。
6. 以隔離 fake remote 或注入 runner 驗證 push 決策，不接觸真實 GitHub。
7. 更新 README、`progress.md` 與 `todo.md`。

真實 `ai-digest deploy` 會 push 並可能觸發 Pages deployment，因此即使自動化與本機 gates 全部通過，仍須取得使用者再次明確授權才可執行。只有真實 workflow 與公開 smoke 均成功後，才能在進度文件中把 deploy 完整標記為完成。

## 9. 非目標

- 不自動建立或修改摘要。
- 不自動提交任何檔案。
- 不提供 branch、remote、site URL、workflow name、dist path 或 Pages base path override。
- 不透過 `workflow_dispatch` 強制重新部署同步 commit。
- 不新增 PDF、OCR、標籤篩選、登入內容、私人內容、完整討論串、網站後台、帳號或常駐服務。
