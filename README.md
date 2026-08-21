# AI Digest

AI Digest 是一套在本機執行的公開內容摘要工具。目前支援可直接讀取的公開網頁與公開 YouTube 單支影片，經繁體中文結構化摘要、分類與 Schema 驗證後儲存為本機 JSON，再由 Astro 建置靜態網站。

完整 MVP 仍要加入無須登入的公開社群單篇貼文。分類模型已通過固定評估；YouTube 字幕與音訊轉錄路徑已有自動化覆蓋，但真實有字幕與無字幕影片驗收狀態以 `progress.md` 為準。PDF／論文、OCR 與標籤篩選是核心 MVP 穩定後才評估的選配項目。

## 環境需求

- Windows PowerShell
- Python 3.12 以上
- Node.js 22.12.0 以上與 npm
- 只有執行真實 `add` 時才需要所選摘要 provider 的 API 金鑰
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

## 本機設定

金鑰只設在目前 PowerShell 進程，不得寫入 repository。摘要 provider 設定如下：

Gemini is the default provider. Configure Gemini explicitly in PowerShell:

```powershell
$env:AI_DIGEST_PROVIDER = 'gemini'
$env:GEMINI_API_KEY = '<your-gemini-api-key>'
$env:GEMINI_MODEL = 'gemini-3.6-flash' # optional; this is the default
```

To use OpenAI explicitly:

```powershell
$env:AI_DIGEST_PROVIDER = 'openai'
$env:OPENAI_API_KEY = '<your-openai-api-key>'
$env:OPENAI_MODEL = 'gpt-5-mini' # optional; this is the default
```

There is no automatic fallback between providers. `add` requires only the API key for the selected provider. Local `list`, `show`, `archive`, and `publish` commands do not require either provider key.

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
```

`add` 處理可直接讀取的公開 HTML 文章與受支援的公開 YouTube 單支影片；遇到登入、付費牆、私有位址或其他不可讀來源會明確失敗。

## YouTube 公開影片

先以你使用的系統套件管理器或官方發行方式安裝 `yt-dlp` 與 FFmpeg，確認兩個可執行檔都在系統 `PATH`：

```powershell
yt-dlp --version
ffmpeg -version
```

YouTube 擷取採字幕優先：人工字幕優先於自動字幕，只有完全沒有可用字幕時，才會下載公開音訊、由 FFmpeg 分段，並送至 OpenAI 語音轉文字 API。預設影片上限為兩小時（`7200` 秒），超過上限時會在下載音訊前停止。可在本機調整以下設定：

```powershell
$env:AI_DIGEST_TRANSCRIPTION_MODEL = 'gpt-transcribe'
$env:AI_DIGEST_TRANSCRIPTION_CHUNK_SECONDS = '600'
$env:AI_DIGEST_YOUTUBE_MAX_DURATION_SECONDS = '7200'
```

`OPENAI_API_KEY` 只在影片確實需要音訊轉錄時才延遲檢查；有可用字幕且摘要 provider 為 Gemini 時不需要 OpenAI 金鑰。無字幕而缺少該金鑰時，系統會在下載音訊前以 `MISSING_API_KEY` 失敗。

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

兩種建置的輸出都位於 `site/dist`。部署前也可在 repository 根目錄掃描追蹤檔案與建置輸出：

```powershell
python scripts/verify_deployment.py --tracked --dist site/dist --base /AI-Summary/
```

## GitHub Pages 操作

公開網址是 <https://yamopeng0918.github.io/AI-Summary/>。`.github/workflows/deploy-pages.yml` 會在 push 到 `master` 時自動觸發，也可到 GitHub repository 的 **Actions → Deploy to GitHub Pages → Run workflow** 手動觸發。最新已記錄的部署為 workflow run `31674616177`，成功部署 commit `7f7dc1ebd8fcb3e06ee79d748d5338f246aca0d1`，公開首頁與 demo 詳情頁均已通過 smoke acceptance。

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
