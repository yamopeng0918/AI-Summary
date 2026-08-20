# 分類器資料審核指南

## 目前審核狀態

`data/classifier/training.csv` 目前共有 180 筆資料，六個分類在每個批次各 10 筆：

- 批次一 60 筆已依使用者明確決定標為 `approved`。
- 批次二 60 筆已依使用者明確決定標為 `approved`。
- 批次三 60 筆為 `pending`，等待逐列審核；本批次不得先行納入最終 cohort、訓練或正式評估。

審核批次三時，每一列都應依序核對公開來源頁面、`sourceTitle`、繁體中文 `text`、`label` 與 `rationale`。審核結果遵循以下規則：

approved：只有在使用者或審核者明確逐列同意後，才能將 `reviewStatus` 改為 `approved`；不得依推測、批次操作或未明示的同意核准。來源可直接讀取、內容轉述正確、主分類明確。
rejected：保留原列並在 reviewNote 說明原因，不進入訓練。
修訂：保留退件列，另以新 id 新增 pending 替代列。

審核既有列時只能修改 `reviewStatus` 與 `reviewNote`。不得改寫已審核列的 ID、來源、文字、分類或理由。需要更換來源或修訂內容時，應保留被退件列，並新增具有唯一 ID、唯一公開來源網址及 `pending` 狀態的替代列。

## 離線計數

以下命令只會使用 `load_dataset` 讀取並驗證 CSV 結構，不會連線外部服務。請在 repository 根目錄執行；若專案 Python 環境已啟用或已在 `PATH` 上，使用第一個指令：

```powershell
$env:PYTHONPATH = "src"
python -c "import json; from collections import Counter; from pathlib import Path; from ai_digest.classifiers.dataset import load_dataset; categories=tuple(json.loads(Path('data/categories.json').read_text(encoding='utf-8'))); rows=load_dataset(Path('data/classifier/training.csv'), categories); print('rows:', len(rows)); print('status:', dict(sorted(Counter(r.review_status for r in rows).items()))); print('category:', {category: sum(r.label == category for r in rows) for category in categories})"
```

若從 worktree 審核且沒有 worktree-local `.venv`，可選擇直接使用主要 checkout 的解譯器（此 worktree 位於 `.worktrees\\classifier-model` 時）：

```powershell
$env:PYTHONPATH = "src"
& '..\\..\\.venv\\Scripts\\python.exe' -c "import json; from collections import Counter; from pathlib import Path; from ai_digest.classifiers.dataset import load_dataset; categories=tuple(json.loads(Path('data/categories.json').read_text(encoding='utf-8'))); rows=load_dataset(Path('data/classifier/training.csv'), categories); print('rows:', len(rows)); print('status:', dict(sorted(Counter(r.review_status for r in rows).items()))); print('category:', {category: sum(r.label == category for r in rows) for category in categories})"
```

批次三送審時，預期為 180 列、`approved` 120 筆、`pending` 60 筆，整體每類 30 筆且每個批次每類各 10 筆。審核過程可反覆執行此計數命令確認狀態。

最終 cohort 驗證會要求 180 筆已核准資料且每類正好 30 筆；批次三尚未取得明確核准，因此目前不要執行最終 cohort 驗證、內容雜湊、分類器訓練或正式評估。
