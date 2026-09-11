# AI Digest 結案報告

交付：[AI-Digest-結案報告.pptx](output/AI-Digest-結案報告.pptx)

九頁、16:9，包含真實網站截圖、原生可編輯文字／流程圖／數據圖表，以及繁體中文講者備註。講稿目標 380 秒，尚未真人試講。採系統 Microsoft JhengHei 字型，未內嵌字型；其他電腦須有相容字型才能維持相同換行。

## 依據與範圍

- [核准設計](../superpowers/specs/2026-09-05-ai-digest-closure-powerpoint-design.md)
- [文案、講稿與逐頁來源](ai-digest-closure-slide-content.md)
- 2026-09-05 使用者明確允許改用本機其他工具製作與驗證。
- 截圖來自既有 `site/dist` 的本機網站，並非重新執行公開部署。數據引用原始分類評估及既有產品驗收紀錄。

## 驗證結果（2026-09-05）

- PPTX 與 LibreOffice 轉出 PDF 各 9 頁；9 份內嵌備註均含 Sources。
- 第 7 頁為原生圖表，資料為 91.6666666667、16.6666666667，顯示四捨五入後百分比。
- 畫布外形狀 0、文字框相交 0；渲染文字與原生文字比對無遺失。
- 逐頁 PNG 已檢視，字型、頁碼、截圖、文字換行與圖表標示無未解決問題。
- 已知憑證格式掃描未命中；沒有讀取真實 `.env`，也未將私人路徑放入投影片。
- 2026-09-08 首頁修訂：加入「課程名稱：非結構型資料的分析案例」，報告日期改為「2026 年 9 月 8 日」。重新渲染與驗證通過；第 2～9 頁及全部講者備註 XML 與修訂前一致。
- 2026-09-08 末頁修訂：統一為暖白底、深墨綠文字、珊瑚紅數字與灰綠輔助文字。渲染與驗證通過；第 1～8 頁及全部講者備註 XML 與此次修改前一致。
- 目前 PPTX SHA-256：`9b8c19072b26275ca1b1157b963f41b09bdb3cd127ce8eec03b9a1cb3c92ba94`。
- 檢查使用 LibreOffice／PDFium，未在 Microsoft PowerPoint 應用程式內開啟驗收。LibreOffice 雖輸出 Python prefix 診斷，但轉檔 exit 0，九頁 PDF 與文字比對均成功。

## 重製方式

這些腳本只用於製作此份文件，不屬於產品 CLI。由 repository root 執行，需本機 `python-pptx`、Pillow、Edge、LibreOffice，以及 `.build/python-deps` 中的 pypdfium2；不變更專案 Python／npm dependencies。

1. 建立 `docs/reports/.build/www/AI-Summary`、`.build/assets`、`.build/rendered`，將 `site/dist` 複製到本機網站目錄。
2. 執行 `python -m http.server 8765 --bind 127.0.0.1 --directory docs/reports/.build/www`。
3. 執行 `powershell -NoProfile -File docs/reports/capture-screenshots.ps1`。腳本以隔離 browser profiles 無視窗擷取，不使用個人瀏覽器 session。
4. 執行 `python docs/reports/build-presentation.py`。
5. 以本機 LibreOffice 的 `soffice.com --headless --convert-to pdf --outdir` 轉換 PPTX 至 `.build/rendered`；使用 `.build/lo-profile` 作為獨立 UserInstallation。
6. 執行 `python docs/reports/verify-presentation.py`，再逐頁檢視 `.build/rendered/slide-01.png` 至 `slide-09.png`。

暫存資料與第三方工具保存在 `.build/`，已忽略，不納入交付或 Git。PPTX 已內嵌全部截圖，不依賴暫存素材才能開啟。
