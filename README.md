# AI Digest

AI Digest 是一套在本機執行的公開內容摘要工具。目前的第一個可交付里程碑支援「可直接讀取的公開網頁 → 繁體中文結構化摘要 → 本機 JSON → Astro 靜態網站」。

完整 MVP 仍要加入 YouTube 公開影片、無須登入的公開社群單篇貼文、可量化的分類模型與 GitHub Pages 部署。PDF／論文、OCR 與標籤篩選是核心 MVP 穩定後才評估的選配項目。

## 環境需求

- Windows PowerShell
- Python 3.12 以上
- Node.js 22.12.0 以上與 npm
- 只有執行真實 `add` 時才需要 OpenAI API 金鑰

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

金鑰只設在目前 PowerShell 進程，不得寫入 repository：

```powershell
$env:OPENAI_API_KEY = '<your-openai-api-key>'
$env:OPENAI_MODEL = 'gpt-5-mini' # 選用
```

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

`add` 只處理可直接讀取的公開 HTML 文章，遇到登入、付費牆、私有位址或其他不可讀來源會明確失敗。目前 CLI 使用 `FixedClassifier` 只是開發期串接邊界，不是已完成的分類模型。正式分類器必須以可重現評估記錄 Accuracy、Macro F1、混淆矩陣與最大類基準，而且測試 Accuracy 必須嚴格高於該基準。

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

開發伺服器會在終端顯示本機網址。產生靜態網站：

```powershell
Set-Location site
npm.cmd run build
```

輸出位於 `site/dist`。目前尚未設定或執行遠端 GitHub Pages 部署。

`npm.cmd ci` 的目前依賴狀態會顯示 `esbuild@0.28.2` 與 `esbuild@0.25.12` 安裝 script 尚未核准的通知；本專案沒有授權或執行這些 script。不要在未審查前自行批准。

## 目前範圍與後續

本里程碑已建立公開網頁擷取、OpenAI 結構化摘要邊界、JSON Schema 驗證與儲存、本機 CLI，以及 Astro 列表、詳情、搜尋、分類篩選與日期排序。

以下是後續里程碑：

- 訓練並驗收優於最大類基準的分類模型。
- YouTube 有字幕與無可用字幕流程。
- 無須登入的公開社群單篇貼文。
- GitHub Pages 遠端設定與獨立部署指令。
- 核心 MVP 穩定後才評估 PDF／論文、OCR 與標籤篩選。
