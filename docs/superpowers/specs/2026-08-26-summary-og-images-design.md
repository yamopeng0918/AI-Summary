# AI Digest 摘要 OG 圖設計規格

## 1. 目標與核准範圍

每篇已發布摘要在 Astro 正式建置時自動產生一張專屬的 1200 × 630 PNG。圖片同時用於：

- 摘要詳情頁的 Open Graph 與 Twitter Card metadata。
- 首頁摘要卡片的預覽圖。

圖片不在摘要詳情正文重複顯示。本功能不修改摘要 Schema、不呼叫外部生成式圖片服務，也不將圖片生成責任放入 Python CLI 或儲存層。

## 2. 視覺方向

採用核准的「編輯刊物風」：

- 暖白背景、深綠主文字與橘色頂端識別線。
- 左上為 `AI DIGEST`，右上為摘要分類。
- 中央以繁體中文標題作為主要視覺層級。
- 標題下方顯示摘要前 1～2 行。
- 底部優先顯示非空作者；沒有作者時顯示 `canonicalUrl` 的 hostname，旁邊顯示 `WEB`、`YOUTUBE` 或 `SOCIAL`。

標題與摘要使用確定性的換行、字級級距及最大行數。超過安全上限時以省略號截斷，不得溢出 1200 × 630 畫布。首頁卡片以完整文章標題作為圖片 `alt`。

為避免 Windows 與 GitHub Actions 的字型差異，repository 在 `site/src/assets/fonts/` 納管 OFL-1.1 授權、`NotoSerifTC-Regular.ttf`（400）及 `NotoSerifTC-Bold.ttf`（700）兩個靜態 Noto Serif TC TTF 與其授權文件。渲染器只能使用該專案內字型，不依賴作業系統字型或建置時網路下載。

## 3. 架構與元件

### 3.1 靜態圖片端點

新增 Astro 靜態端點 `site/src/pages/og/[id].png.ts`。`getStaticPaths()` 使用既有 `loadPublishedSummaries()`，因此只為通過 Schema 驗證且狀態為 `published` 的摘要建立路由：

```text
/AI-Summary/og/<id>.png
```

本機未設定 Pages base 時則為 `/og/<id>.png`。端點回應 `Content-Type: image/png`，不建立常駐後端。

### 3.2 確定性圖片渲染器

新增獨立 TypeScript 模組，接收已驗證的摘要顯示資料並回傳 PNG bytes。模組使用 Satori 將版型與已載入的 Noto Serif TC 字型轉為 SVG，再使用專案直接依賴的 Sharp 轉為 1200 × 630 PNG。

渲染器只負責排版及編碼，不讀取摘要目錄、不判斷發布狀態，也不建立頁面 URL。文字正規化、來源標籤、換行及截斷須為可獨立測試的純函式；新增的每個正式函式都必須有測試。

### 3.3 路徑與 metadata

新增共用 OG 圖路徑 helper，延續既有 `BASE_URL` 路徑規則。首頁用相同 helper 產生卡片 `<img src>`；詳情頁使用 `Astro.site` 與 base-aware 路徑組合完整 HTTPS 圖片 URL。

`BaseLayout` 擴充可選的 description、canonical URL、OG 圖 URL及頁面類型 props。摘要詳情頁提供：

- `og:title`
- `og:description`
- `og:type=article`
- `og:url`
- `og:image`
- `og:image:width=1200`
- `og:image:height=630`
- `og:image:alt`
- `twitter:card=summary_large_image`
- `twitter:title`
- `twitter:description`
- `twitter:image`

首頁沿用現有基本 metadata，不新增每篇摘要專屬 OG metadata。

## 4. 資料流

```text
data/summaries/*.json
  → loadPublishedSummaries（Schema 驗證與 published 篩選）
    ├─ Astro 首頁卡片 → /og/<id>.png
    ├─ Astro 詳情頁 metadata → 絕對 /og/<id>.png URL
    └─ 靜態 PNG 端點 → OG renderer → Satori SVG → Sharp PNG
```

圖片只存在於 Astro 建置輸出 `site/dist/og/`，不寫回 `data/summaries`，也不將生成的 PNG 納入 Git 追蹤。重新建置會自然移除已下架摘要的公開圖片，避免 prebuild 資產殘留。

## 5. 首頁卡片行為

每張現有摘要卡片在 metadata 區塊前加入 OG 圖：

- 使用原生 `<img>`，設定 `width="1200"`、`height="630"`、`loading="lazy"` 與 `decoding="async"`。
- CSS 使用 `aspect-ratio: 1200 / 630`、`width: 100%` 與 `object-fit: cover`，避免版面位移。
- 圖片與標題連到同一摘要詳情頁。
- 搜尋、分類、排序與空狀態沿用現有行為；圖片不進入搜尋索引資料。

## 6. 錯誤與安全行為

圖片生成採 fail-closed：

- 字型檔缺失或無法載入。
- 摘要資料未通過既有 Schema 驗證。
- Satori 或 Sharp 渲染失敗。
- 輸出不是非空 PNG，或尺寸不是 1200 × 630。

發生上述情形時，Astro 正式建置必須失敗，不得部署缺圖或 metadata 指向不存在圖片的頁面。錯誤不得包含摘要目錄外的檔案內容、環境變數或憑證值。

所有內容均來自已驗證摘要欄位；輸入文字交由渲染器處理，不拼接成可執行 HTML。圖片生成不進行外部 HTTP 請求。

## 7. 測試驅動與驗收

依 TDD 順序實作：先建立會因缺少行為而失敗的最小測試，再加入最小正式實作。

自動化覆蓋：

- OG 圖路徑在 `/` 與 `/AI-Summary/` base 下均正確。
- 只為 `published` 摘要建立圖片路由。
- 標題與摘要的換行、縮放、截斷、繁體中文及 XML 特殊字元處理。
- 回應 MIME 為 `image/png`、內容非空、PNG 尺寸為 1200 × 630。
- 摘要詳情頁包含完整、絕對且 base-aware 的 Open Graph、Twitter Card 與 canonical metadata。
- 首頁卡片圖片包含正確 `src`、`alt`、尺寸、lazy loading 與詳情連結。
- archived 與無效摘要保持既有 fail-closed 行為。

完成後執行：

1. 相關 Vitest 測試。
2. 完整前端測試。
3. `astro check`。
4. 正式 Pages build。
5. deployment verifier 與 `site/dist` 敏感資料掃描。
6. `git diff --check`。
7. 人工檢視至少一張包含中文長標題的實際 PNG，確認沒有缺字、裁切、溢出或低對比。

## 8. 非目標

- 不使用 Gemini、OpenAI 或其他付費圖片 API。
- 不為 archived 摘要保留公開 OG 圖。
- 不修改摘要 JSON Schema 或加入圖片欄位。
- 不在 Python `ai-digest add` 階段生成圖片。
- 不在摘要詳情正文顯示 OG 圖。
- 不新增動態圖片服務、後端、資料庫或使用者自訂版型。
