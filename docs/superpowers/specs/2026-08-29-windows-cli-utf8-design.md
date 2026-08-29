# Windows CLI UTF-8 輸出相容性設計

## 目標

修正 Windows PowerShell 使用 CP950 等非 UTF-8 互動式終端時，`ai-digest list` 與 `ai-digest show` 因摘要標題或內容含無法編碼字元而拋出 `UnicodeEncodeError` 的問題。修正後，互動式終端應完整顯示繁體中文、簡體中文及其他 Unicode 內容，不要求使用者預先設定 `PYTHONUTF8=1`。

本變更只調整 CLI 的終端輸出邊界，不改變摘要 Schema、JSON 儲存格式、命令參數、資料內容、來源解析器、摘要服務或網站。

## 已確認根因

- `_emit()` 使用 `json.dumps(..., ensure_ascii=True)`，因此進度與結構化錯誤事件只含 ASCII，能安全寫入 CP950。
- `list` 直接以 `typer.echo()` 輸出包含記錄標題與分類的 Unicode 字串。
- `show` 以 `ensure_ascii=False` 產生完整 Unicode JSON，再直接交給 `typer.echo()`。
- 當 Windows 互動式 stdout 的文字編碼為 CP950，且內容含 CP950 無法表示的字元時，寫入階段拋出 `UnicodeEncodeError`。以 CP950 輸出替身執行現有正式 CLI，已重現 `list` 與 `show` 均以 exit code 1 失敗。

## 核准方案

在 CLI 進入點建立一個小型終端設定邊界：只在 Windows 且目標標準串流為互動式 TTY 時，將 stdout 與 stderr 的文字編碼重新設定為 UTF-8。設定完成後沿用既有 Typer／Click 輸出流程，讓 `list` 保持目前的 tab 分隔人類可讀格式，`show` 保持未跳脫的合法 JSON。

非互動式串流（例如重新導向到檔案、pipe 或測試捕捉串流）不得被強制改碼，避免破壞呼叫端既有協定。非 Windows 平台不得改變串流設定。

若串流不是可重新設定的文字串流，或不提供 `reconfigure()`，設定函式應安全略過；不得因嘗試改善終端編碼而讓 CLI 無法啟動。這個容錯僅限於偵測到不支援重新設定的串流，不得吞掉命令本身的輸出或資料錯誤。

## 元件與資料流

1. CLI 啟動時取得 stdout 與 stderr。
2. 終端設定函式判斷平台及每個串流的 `isatty()`。
3. Windows 互動式串流呼叫 `reconfigure(encoding="utf-8")`；其他串流保持不變。
4. Typer 命令照既有方式讀取 repository 並輸出內容。
5. `list`、`show`、進度事件與結構化錯誤共用已設定的終端環境，不在各命令重複編碼邏輯。

此邊界屬於 CLI 組合層，不放入 repository、domain model 或來源解析器，維持既有架構責任。

## 公開行為

- `ai-digest list` 的欄位、順序及 tab 分隔格式不變。
- `ai-digest show <id>` 仍輸出可由 JSON parser 讀取的完整記錄。
- `add`、`archive`、`publish` 與 `evaluate-classifier` 的 ASCII-safe 結構化事件格式不變。
- Windows 互動式終端不再需要 `PYTHONUTF8=1` 才能顯示 repository 中的 Unicode 內容。
- pipe、重新導向與非 Windows 執行環境的串流編碼不由本功能改寫。

## 錯誤與安全

- 不輸出或記錄環境變數、密鑰、Cookie 或 `.env` 內容。
- 不把 Unicode 輸出問題轉換成摘要領域錯誤；它是 CLI 啟動時的環境相容性設定。
- 不使用 `errors="ignore"` 或文字替換，避免靜默遺失摘要內容。
- 不全域修改 Windows code page，也不持久修改 PowerShell profile 或使用者環境。

## TDD 與驗收

依 Red-Green-Refactor 實作：

1. 先新增最小單元測試，證明 Windows 互動式 stdout／stderr 會以 UTF-8 重新設定；測試在缺少行為時必須以預期 assertion 失敗。
2. 新增非互動式串流與非 Windows 平台不重新設定的測試。
3. 新增不支援 `reconfigure()` 的互動式串流可安全略過的測試。
4. 寫入最小正式實作並重跑 focused CLI tests。
5. 以含 CP950 無法表示字元的真實 `SummaryRecord` 驗證 `list` 與 `show`；`show` 輸出仍須能由 `json.loads()` 解析且內容未遺失。
6. 執行完整 Python test suite、`git diff --check`、追蹤檔案敏感資料掃描，並更新 README、`progress.md` 與 `todo.md`。

不以真實網路、付費 API 或修改使用者 PowerShell 設定作為自動化測試前提。

## 非目標

- 不修正或持久設定使用者的 `PATH`。
- 不新增 CLI 命令或輸出格式選項。
- 不替所有第三方子程序重新解碼輸出。
- 不變更 Pages、Astro、摘要資料或分類模型。
- 不支援登入內容、私人內容或其他超出核心 MVP 的來源。
