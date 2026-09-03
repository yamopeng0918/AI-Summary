# AI Digest

AI Digest 是一套在本機執行的公開內容摘要工具。目前支援可直接讀取的公開網頁與公開 YouTube 單支影片，經繁體中文結構化摘要、分類與 Schema 驗證後儲存為本機 JSON，再由 Astro 建置靜態網站。

完整 MVP 仍要加入無須登入的公開社群單篇貼文。分類模型已通過固定評估；YouTube 字幕與音訊轉錄路徑已有自動化覆蓋，但真實有字幕與無字幕影片驗收狀態以 `progress.md` 為準。PDF／論文、OCR 與標籤篩選是核心 MVP 穩定後才評估的選配項目。

## 環境需求

- Windows PowerShell
- Python 3.12 以上
- Node.js 22.12.0 以上與 npm
- 只有執行真實 `add` 或 `regenerate` 時才需要所選摘要 provider 的 API 金鑰
- 處理 YouTube 時需要 `yt-dlp` 在 `PATH`；無可用字幕時另需 FFmpeg 在 `PATH`

## Python 安裝

在 repository 根目錄執行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

啟用虛擬環境後，`ai-digest` 指令應可直接使用。目前這台開發機器的 user-site Python Scripts 目錄未在 `PATH` 中；若跳過虛擬環境而安裝到 user site，裸用 `ai-digest` 可能找不到指令。請改用上述 `.venv` 流程，或將對應 Scripts 目錄加入 `PATH`。

若 PowerShell 的 Execution Policy 阻擋 `Activate.ps1`，不必永久降低安全設定，可直接執行虛擬環境中的 CLI：

```powershell
& '.\.venv\Scripts\ai-digest.exe' list
```

在 Windows PowerShell 或 Windows Terminal 執行 `ai-digest` 時，CLI 會自動將互動式 stdout 與 stderr 設為 UTF-8，讓 `list` 與 `show` 能完整顯示繁體中文、簡體中文及其他 Unicode 內容，不必預先設定 `PYTHONUTF8=1`。這項設定只作用於互動式終端；pipe 或重新導向時，CLI 會維持呼叫端既有的編碼。

若要在目前 PowerShell 視窗使用裸 `ai-digest`，可只調整目前 process 的 `PATH`，不修改系統設定：

```powershell
$env:Path = "$(Resolve-Path '.\.venv\Scripts');$env:Path"
ai-digest list
```

也可自行把 repository 的 `.venv\Scripts` 絕對路徑加入使用者 `PATH`；持久更新後需關閉並重新開啟 PowerShell。

## 本機設定

金鑰只設在目前 PowerShell 進程，不得寫入 repository。摘要 provider 設定如下：

Gemini is the default provider. Configure Gemini explicitly in PowerShell:

```powershell
$env:AI_DIGEST_PROVIDER = 'gemini'
$env:GEMINI_API_KEY = '<your-gemini-api-key>'
$env:GEMINI_MODEL = 'gemini-3.6-flash' # optional; this is the default
$env:GEMINI_TRANSCRIPTION_MODEL = 'gemini-3.6-flash' # optional; no-caption YouTube default
```

To use OpenAI explicitly:

```powershell
$env:AI_DIGEST_PROVIDER = 'openai'
$env:OPENAI_API_KEY = '<your-openai-api-key>'
$env:OPENAI_MODEL = 'gpt-5-mini' # optional; this is the default
$env:OPENAI_TRANSCRIPTION_MODEL = 'gpt-transcribe' # optional; no-caption YouTube default
```

There is no automatic fallback between providers. `AI_DIGEST_PROVIDER` selects both structured summarization and no-caption YouTube audio transcription; `add` and `regenerate` require only the API key for that selected provider. Local `list`, `show`, `archive`, `publish`, and `edit` commands do not require either provider key.

可用 `AI_DIGEST_SUMMARY_ROOT` 將 JSON 寫入其他本機目錄；未設定時使用 `data/summaries`。

```powershell
$env:AI_DIGEST_SUMMARY_ROOT = 'C:\path\to\summaries'
```

## CLI

```powershell
ai-digest add 'https://example.com/readable-public-article'
ai-digest list
ai-digest show '<summary-id>'
ai-digest archive '<summary-id>'
ai-digest publish '<summary-id>'
ai-digest edit '<summary-id>'
ai-digest regenerate '<summary-id>'
```

`add` 處理可直接讀取的公開 HTML 文章與受支援的公開 YouTube 單支影片；遇到登入、付費牆、私有位址或其他不可讀來源會明確失敗。

## 本機編輯與重新產生

`edit` 會在外部文字編輯器開啟一筆既有摘要的暫存 UTF-8 JSON；編輯器關閉後才驗證並更新原記錄。需要等待 GUI 編輯器關閉時，可在目前 PowerShell 設定：

```powershell
$env:VISUAL = "code --wait"
ai-digest edit <record-id>
ai-digest regenerate <record-id>
```

編輯器依序選擇 `VISUAL`、`EDITOR`，兩者皆未設定時 Windows 使用 `notepad.exe`。設定中含空白的執行檔路徑必須加引號；命令會以參數陣列、`shell=False` 執行並等待結束。

`edit` 可改動 `title`、`author`、`sourcePublishedAt`、`summary`、`keyPoints`、`category`、`tags`、`editorial` 與 `status`。`schemaVersion`、`id`、`canonicalUrl`、`sourceType`、`createdAt` 是受保護欄位，必須維持原值；使用者輸入的 `updatedAt` 會被忽略並改由系統的 Asia/Taipei 時鐘寫入。編輯結果必須是完整有效的 JSON 並通過 `SummaryRecord` Schema 驗證，才會以原子覆寫更新；編輯器失敗、JSON／Schema 驗證失敗、受保護欄位改動或寫入失敗時，既有 JSON 保持不變，暫存檔也會清理。

`regenerate` 以既有記錄的 `canonicalUrl` 重新擷取、重新摘要與重新分類，保留原本的 `id`、`createdAt` 與 `status`。它使用 `AI_DIGEST_PROVIDER` 所選 provider，且只要求該 provider 的金鑰；指令在擷取與重複 URL 預檢成功後會進行一次付費摘要呼叫，沒有額外互動式確認。任一擷取、摘要、分類、驗證或儲存階段失敗都不覆寫既有 JSON。兩個指令都只改本機資料，不會自動提交、推送或部署 GitHub Pages。

## YouTube 公開影片

先以你使用的系統套件管理器或官方發行方式安裝 `yt-dlp` 與 FFmpeg，確認兩個可執行檔都在系統 `PATH`：

```powershell
yt-dlp --version
ffmpeg -version
```

YouTube 擷取採字幕優先：人工字幕優先於自動字幕，只有完全沒有可用字幕時，才會下載公開音訊、由 FFmpeg 分段，並交給 `AI_DIGEST_PROVIDER` 所選的 Gemini 或 OpenAI 轉錄器。預設影片上限為兩小時（`7200` 秒），超過上限時會在下載音訊前停止。可在本機調整以下設定：

```powershell
$env:GEMINI_TRANSCRIPTION_MODEL = 'gemini-3.6-flash'
$env:OPENAI_TRANSCRIPTION_MODEL = 'gpt-transcribe'
$env:AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS = '600'
$env:AI_DIGEST_TRANSCRIPTION_MAX_CHUNK_BYTES = '25165824'
$env:AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS = '7200'
```

音訊轉錄器只在影片確實沒有可用字幕時才延遲建立。Gemini 路徑只使用 `GEMINI_API_KEY`，透過 Files API 逐段上傳、轉錄，並在成功、失敗或中斷時嘗試刪除每個遠端暫存檔；OpenAI 路徑只使用 `OPENAI_API_KEY`。兩條路徑都不會自動 fallback 到另一個 provider。缺少所選 provider 金鑰時，系統會在下載音訊前以 `MISSING_API_KEY` 失敗。

音訊同時受分段秒數與 24 MiB 的預設檔案大小上限保護。分段超過上限時會以 `MEDIA_CHUNK_TOO_LARGE` 安全停止；若無法檢查分段檔案，則回報可重試的 `MEDIA_DOWNLOAD_FAILED`。這兩種錯誤都不會輸出暫存路徑或底層作業系統錯誤。

只支援公開、無須登入且已完成的單支影片。頻道頁、播放清單頁與無影片 ID 的 URL 會回報 `UNSUPPORTED_YOUTUBE_URL`；私人、會員限定、刪除或地區限制影片會回報 `CONTENT_UNAVAILABLE`；需要登入或年齡驗證、直播中或尚未開始、以及超時長內容也會明確失敗。本專案不支援 Cookie、登入資料、代理伺服器或任何存取繞過參數。

## 分類模型評估與啟用

先依下列方式安裝含分類器的開發依賴，再執行評估：

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ai-digest evaluate-classifier
```

評估只使用 `data/classifier/training.csv` 中 `reviewStatus=approved` 的資料。正式評估前必須有六個既有分類各 30 筆、共 180 筆已審查資料；`pending` 與 `rejected` 資料保留為審查紀錄，但不得進入訓練或評估。評估會記錄 Accuracy、Macro F1、混淆矩陣與最大類基準；只有測試 Accuracy 嚴格高於該基準時，才會產生可供正式分類使用的模型。

評估報告與受 repository 控制的正式 artifact 路徑固定如下：

- `data/classifier/evaluation.json`
- `models/classifier.joblib`
- `models/classifier-manifest.json`
- `data/categories.json`

目前已接受的固定評估使用 180 筆 approved 資料與 seed `42`，其中 144 筆訓練、36 筆 held-out 測試。Accuracy 為 `0.9166666666666666`、Macro F1 為 `0.917915417915418`，嚴格高於最大類基準 Accuracy `0.16666666666666666`；完整可重現證據位於 `data/classifier/evaluation.json`，資料集內容雜湊為 `1b65281c6dda2a60b800442140129915ff84d292da0e4fdfa69246b50544459c`。

生產 `add` 和 `scripts/publish_url.py` 僅載入這組固定 artifact，沒有環境變數、CLI 參數或靜默回退可改用其他模型。模型尚未通過評估或 artifact 不存在時，在已完成摘要 provider 設定後，建立摘要工作流程會回報結構化 `classify`／`MODEL_NOT_FOUND` 錯誤；不會開始擷取或摘要，也不會寫入摘要 JSON。`FixedClassifier` 僅保留給測試與明確的本機開發組裝，不能作為生產回退。

## One-command publishing script

Run the end-to-end local publishing workflow for one public article URL with the project venv Python:

```powershell
& '.\.venv\Scripts\python.exe' scripts/publish_url.py 'https://example.com/public-article'
```

If the venv is already active, you can run:

```powershell
python scripts/publish_url.py 'https://example.com/public-article'
```

The script uses the approved repository defaults:

- summaries under `data/summaries`
- GitHub repository `yamopeng0918/AI-Summary`
- Pages root `https://yamopeng0918.github.io/AI-Summary/`
- workflow name `Deploy to GitHub Pages`

It prints the published summary ID, commit SHA, workflow URL, and public detail URL on success. It reports safe structured errors on stderr without echoing provider keys.

## 測試

在 repository 根目錄執行：

```powershell
python -m pytest
```

日常自動測試使用本地 HTML fixture、HTTP mock 與確定性摘要替身，不需要網路或付費 API。

## Astro 網站

```powershell
Set-Location site
npm.cmd ci
npm.cmd test
npm.cmd run dev
```

開發伺服器會在終端顯示本機網址。一般本機建置：

```powershell
Set-Location site
npm.cmd run build
```

GitHub Pages 專用的完整本機 gate 會同時執行 Astro 檢查、建置及 `/AI-Summary/` base-path 連結驗證：

```powershell
Set-Location site
npm.cmd run build:pages
```

若已完成 Python CLI 安裝，可由 repository 根目錄使用單一的 GitHub Pages 本機 gate：

```powershell
ai-digest build-site
```

此指令依序執行既有 Node.js dependencies 的 `npm.cmd run build:pages`，再驗證 tracked 檔案與 `site/dist`；不會執行 `npm ci`、Git commit、push、GitHub Actions 或部署，也不會呼叫摘要 provider。`build-site` 會保留 npm／Astro／verifier 的即時診斷輸出，方便人工排錯；上述較低階的 npm 與 verifier 指令仍可作為疑難排解或手動執行的替代方式。

`npm.cmd run build:pages` 會為每筆 `published` 摘要自動建立一張 PNG，輸出至 `site/dist/og/`，供首頁卡片及摘要詳情頁的 Open Graph／Twitter metadata 使用。這些 PNG 與 `site/dist` 的其他內容都是建置 artifact，不是要加入 Git 追蹤的內容；每次部署應由來源資料重新產生。

OG 圖固定使用 repository 內的官方完整 Pan-CJK `NotoSerifCJKtc-Regular.otf`（400）與 `NotoSerifCJKtc-Bold.otf`（700），並保留 OFL-1.1 授權；正常測試與建置不會下載字型。渲染前會對所有顯示字串執行 fail-closed cmap 覆蓋檢查，避免缺字被靜默替換；標題、摘要與來源分別使用保守的 `18`／`40`／`36` 個全形等價字元界限，所有 fitted 行均保持不換行。替換字型時必須同時提供兩個完整靜態 OTF、更新授權文件，並通過完整字串覆蓋測試。

兩種建置的輸出都位於 `site/dist`。部署前也可在 repository 根目錄掃描追蹤檔案與建置輸出：

```powershell
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
```

## GitHub Pages 操作

公開網址是 <https://yamopeng0918.github.io/AI-Summary/>。`.github/workflows/deploy-pages.yml` 會在 push 到 `master` 時自動觸發，也可到 GitHub repository 的 **Actions → Deploy to GitHub Pages → Run workflow** 手動觸發。`deploy` CLI 功能驗收的成功部署為 workflow run `33739413130`，對應 head `1d484e493c290eb3a36c496c0829ff18564f8f15`，已於 2026-09-03 由 `ai-digest deploy` 確認為成功；公開首頁與 demo 詳情頁 smoke acceptance 通過。

在 repository root，只有在使用者明確授權這次會造成 Git push 與 GitHub Pages 驗收的實際動作後，才執行：

```powershell
ai-digest deploy
```

`deploy` 只處理已提交的 `master` 內容。它忽略 untracked files，但拒絕 staged 或 unstaged 的 tracked 變更，也拒絕本機落後或與 `origin/master` 分歧的狀態。通過 preflight 後，命令會執行既有的本機 `build-site` gates；只有本機嚴格超前時才以一般 `git push origin master` 推送。若已同步，命令不 push，改用同一 HEAD 已成功的 `Deploy to GitHub Pages` workflow；接著才執行公開網站 smoke 驗證。

`deploy` 的 stdout 與 stderr 嚴格只輸出 JSON Lines。Git、npm／Astro、verifier 與 public smoke 的子程序輸出會被捕捉且不轉送；進度與完成結果寫到 stdout，失敗則在 stderr 寫入單一結構化錯誤。因此可安全交由腳本逐行解析。這不會改變獨立 `build-site` 的即時診斷行為。

這個命令永遠不會建立 commit、force push、以 `workflow_dispatch` 重複觸發 workflow、初始化摘要 provider，或部署非 `master` 分支。它也不會加入、提交或推送 untracked files。只有本機 gate、相同 commit 的 workflow 與公開 smoke 都成功時，才可視為一次部署完成。

部署完成後，在 repository 根目錄執行公開 smoke check：

```powershell
python scripts/smoke_pages.py
```

若 Actions 執行失敗，前往 **Actions → Deploy to GitHub Pages → 該次失敗的 workflow run → Re-run jobs** 重試，並先查看失敗 job 的日誌。後續部署仍應先執行本機 `build:pages`、敏感資料掃描與 smoke checker。

專案已推送至 <https://github.com/yamopeng0918/AI-Summary.git>；只有實際成功的 workflow run 與公開 smoke acceptance 可作為部署完成證據。

`npm.cmd ci` 的目前依賴狀態會顯示 `esbuild@0.28.2` 與 `esbuild@0.25.12` 安裝 script 尚未核准的通知；本專案沒有授權或執行這些 script。不要在未審查前自行批准。

## 目前範圍與後續

本里程碑已建立公開網頁與 YouTube 來源擷取、Gemini 與 OpenAI 結構化摘要邊界、provider-aware CLI、JSON Schema 驗證與儲存，以及 Astro 列表、詳情、搜尋、分類篩選與日期排序。

以下是後續里程碑：

- 以真實公開有字幕與無字幕 YouTube 影片完成手動整合驗收。
- 無須登入的公開社群單篇貼文。
- 核心 MVP 穩定後才評估 PDF／論文、OCR 與標籤篩選。
