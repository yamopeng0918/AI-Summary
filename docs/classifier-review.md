# 分類器資料審核指南

## 批次一狀態

`data/classifier/training.csv` 的批次一共有 60 筆候選資料，六個分類各 10 筆。所有資料目前均為 `pending`，尚未進入訓練或最終評估。

每一列都應依序核對公開來源頁面、`sourceTitle`、繁體中文 `text`、`label` 與 `rationale`。審核結果遵循以下規則：

approved：來源可直接讀取、內容轉述正確、主分類明確。
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

批次一尚未完成審核時，預期為 60 列、`pending` 60 筆、每類 10 筆。審核過程可反覆執行此計數命令確認狀態。

最終 cohort 驗證會要求 180 筆已核准資料且每類正好 30 筆；在三個批次全部完成審核以前，不要執行最終 cohort 驗證或分類器評估。
