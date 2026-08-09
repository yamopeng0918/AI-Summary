# AI Digest GitHub Pages 部署設計

> 日期：2026-08-09
>
> 狀態：已完成對話設計核准，尚未實作或部署

## 目標

將 `site/` 中的 Astro 靜態網站部署至 GitHub Pages，公開網址固定為：

`https://yamopeng0918.github.io/AI-Summary/`

每次推送 `master` 時自動執行完整驗證與部署，並保留手動觸發能力。只有測試、敏感資料掃描與正式建置都成功時，才可發布新的 Pages artifact。

## 範圍

本里程碑包含：

- GitHub Actions 部署 workflow。
- Astro 的 GitHub Pages `site` 與 `base` 設定。
- 支援 `/AI-Summary/` 子路徑的內部連結。
- Python、前端、建置與敏感資料部署門檻。
- 部署後公開首頁與示範摘要頁驗收。
- README、`progress.md` 與 `todo.md` 的部署操作及實際狀態更新。

本里程碑不包含：

- 自訂網域、DNS 或 `CNAME`。
- OpenAI API 金鑰或線上摘要產生。
- 真實公開文章的端到端摘要驗收。
- 正式分類模型、YouTube 或社群來源。
- 自動回滾、刪除摘要 JSON 或建立 `gh-pages` 分支。

目前 repository 中的 `fictional-ai-digest-demo` 示範摘要已獲准在首版 Pages 網站公開展示。

## 官方依據

- Astro 官方建議以 `withastro/action` 建置 GitHub Pages，並為 project site 設定 `site` 與 repository `base`：<https://docs.astro.build/en/guides/deploy/github/>
- GitHub Pages custom workflow 必須上傳 Pages artifact，並以具備 `pages: write` 與 `id-token: write` 權限的 deployment job 發布：<https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages>

實作時使用官方文件當時列出的穩定 action major 版本，並在提交前核對 action 發布來源與版本。

## 部署架構

新增 `.github/workflows/deploy-pages.yml`，觸發條件為：

- 推送至 `master`。
- GitHub Actions 頁面手動執行 `workflow_dispatch`。

workflow 分為兩個 job：

1. `build`
   - checkout repository。
   - 設定符合專案需求的 Python 與 Node 版本。
   - 依鎖定檔安裝 Python 與 npm 依賴。
   - 執行 Python 完整測試、前端測試與敏感資料掃描。
   - 使用 Astro 官方 `withastro/action`，將專案路徑指定為 `site/`。
   - 由 Astro Action 執行正式建置並上傳 GitHub Pages artifact。
2. `deploy`
   - 以 `needs: build` 保證只有 build 成功才執行。
   - 使用 `github-pages` environment，並把 deployment 輸出的公開網址記錄在 environment URL。
   - 使用官方 `actions/deploy-pages` 發布 artifact。

workflow 權限採最小權限：

- `contents: read`
- `pages: write`
- `id-token: write`

部署使用 concurrency group，避免多個 Pages 部署互相覆蓋。新的排隊部署可取代尚未開始的舊部署，但不強制中斷已開始的部署。

GitHub repository 的 Pages Source 必須設定為 GitHub Actions。這是一次性的遠端設定，只有在使用者核准實際部署後才執行。

## Astro 子路徑

`site/astro.config.mjs` 設定：

```js
export default defineConfig({
  output: 'static',
  srcDir: './src',
  site: 'https://yamopeng0918.github.io',
  base: '/AI-Summary',
});
```

`site` 是 GitHub Pages 網域來源，`base` 是 repository project site 的路徑。兩者組合後的公開根網址為 `https://yamopeng0918.github.io/AI-Summary/`。

目前首頁、詳情頁與版面配置含有從 `/` 開始的硬編碼內部連結。實作時新增一個小型路徑 helper，以 Astro 的 `import.meta.env.BASE_URL` 產生首頁及摘要詳情路徑：

- `/AI-Summary/`
- `/AI-Summary/summaries/<id>/`

所有內部連結改用該 helper。原文 `canonicalUrl` 是外部來源網址，不套用 Pages base。

路徑變更採 TDD：先新增最小測試，確認目前程式無法產生核准的 base path；再實作 helper 並修改 Astro 頁面。正式建置後額外檢查生成 HTML，確保內部連結沒有錯誤導向 `https://yamopeng0918.github.io/` 根目錄。

## 驗證門檻

部署前必須全部通過：

1. 以專案開發依賴執行完整 `pytest`。
2. 依 `site/package-lock.json` 安裝 Node 依賴。
3. 執行 Vitest 前端測試。
4. 執行 Astro `check` 與正式靜態建置。
5. 掃描 Git 追蹤檔案與 `site/dist`，拒絕常見 API key、GitHub token、私密金鑰及 `.env` 內容格式。
6. 檢查生成 HTML 的 Pages base path。

workflow 不設定或讀取 OpenAI API 金鑰。部署只讀取 repository 中已通過 Schema 驗證且狀態為 `published` 的摘要 JSON。

目前 npm 依賴狀態曾顯示 `esbuild` 安裝 script 尚未核准的通知。實作 workflow 前必須審查 `esbuild`、`sharp` 與其鎖定版本的建置需求，只允許 Astro 建置必要且來源明確的依賴 script，不加入任意全域批准。

## 部署後驗收

`deploy` 完成後執行有限次重試的 smoke check：

- 公開首頁回傳成功 HTTP 狀態。
- 首頁包含 `AI Digest`。
- 示範摘要詳情頁位於 `/AI-Summary/summaries/20260809-fictional-ai-digest-demo/` 並可讀取。

重試必須有固定次數與等待上限，避免 GitHub Pages 傳播延遲造成無限等待。若 artifact 已發布但 smoke check 最終失敗，workflow 標記失敗並保留日誌；不得自動刪除 JSON、清除本機資料或宣稱部署完成。

## 失敗處理

- 測試、掃描或建置失敗：不得進入 deployment job，既有 Pages 版本繼續服務。
- deployment API 失敗：保留已建置 artifact 與 Actions 日誌，允許透過 `workflow_dispatch` 重試。
- 公開 smoke check 失敗：記錄被檢查網址、HTTP 結果與重試次數，但不得輸出任何憑證。
- 後續部署成功前，不在 `progress.md` 或 `todo.md` 將 GitHub Pages 標記為完成。

## 驗收標準

只有下列條件全部具備，才可宣稱 GitHub Pages 里程碑完成：

- 路徑 helper 測試曾依 TDD 流程由失敗轉為通過。
- Python 與前端完整測試通過。
- Astro 正式建置通過，且生成連結包含 `/AI-Summary/`。
- 追蹤檔案與 `site/dist` 敏感資料掃描通過。
- GitHub Pages Source 為 GitHub Actions。
- deployment workflow 成功發布 `master` 對應 artifact。
- 公開首頁與示範摘要詳情頁 smoke check 通過。
- README、`progress.md`、`todo.md` 已依真實驗證結果同步更新。
