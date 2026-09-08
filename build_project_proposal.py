from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


TEMPLATE = Path(
    r"C:\Users\yamopeng\Downloads\職能學院\提案報告\專案企劃書＿公版.docx"
)
OUTPUT = Path(__file__).resolve().parent / "AI_Digest_專案企劃書.docx"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_repeat_table_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    tbl_header = OxmlElement("w:tblHeader")
    tbl_header.set(qn("w:val"), "true")
    tr_pr.append(tbl_header)


def set_table_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        tag = qn(f"w:{edge}")
        element = borders.find(tag)
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), "B7B7B7")


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.text = ""
    paragraph = cell.paragraphs[0]
    run = paragraph.add_run(text)
    run.bold = bold
    run.font.name = "Microsoft JhengHei"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft JhengHei")
    run.font.size = Pt(10)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def add_bullet(doc: Document, text: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.first_line_indent = Inches(-0.18)
    paragraph.add_run("• " + text)


def add_numbered(doc: Document, text: str) -> None:
    count = getattr(add_numbered, "_count", 0) + 1
    add_numbered._count = count
    paragraph = doc.add_paragraph()
    paragraph.paragraph_format.left_indent = Inches(0.25)
    paragraph.paragraph_format.first_line_indent = Inches(-0.18)
    paragraph.add_run(f"{count}. {text}")


doc = Document(TEMPLATE)

# Preserve the template's styles, margins and section settings, while replacing
# its instructional placeholders with the completed proposal.
body = doc._element.body
sect_pr = body.sectPr
for child in list(body):
    if child is not sect_pr:
        body.remove(child)

title = doc.add_paragraph(style="Heading 1")
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run("專案企劃書")
run.bold = True

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle_run = subtitle.add_run("AI Digest 個人文章摘要與公開閱讀網站")
subtitle_run.bold = True
subtitle_run.font.size = Pt(16)

doc.add_paragraph("專案執行者：＿＿＿＿＿＿＿＿＿＿")
doc.add_paragraph("諮詢講師：＿＿＿＿＿＿＿＿＿＿")
doc.add_paragraph("企劃日期：2026/07/30")

doc.add_heading("1. 我的專案主題", level=3)
doc.add_paragraph(
    "建立一套以個人使用為核心的 AI 文章摘要系統。使用者在本機透過 Codex Skill "
    "提交公開網址，系統自動擷取內容、產生繁體中文摘要並保存，再部署至 GitHub Pages，"
    "讓一般讀者能公開瀏覽、搜尋與篩選摘要。"
)

doc.add_heading("2. 我的專案目標", level=3)
doc.add_paragraph("2-1 製作專案的原因（50–100字）：")
doc.add_paragraph(
    "每天接觸大量網頁、社群貼文、論文與影音內容，閱讀與整理需耗費許多時間。"
    "本專案希望把收集、摘要、分類、保存與發布整合成單一流程，協助自己快速掌握重點，"
    "同時將整理成果轉化為可持續累積與公開查找的知識內容。"
)
doc.add_paragraph("2-2 想達成的專案成果目標（50–100字）：")
doc.add_paragraph(
    "完成一套可處理一般公開網頁、YouTube、文字型 PDF／論文，以及 X、Facebook、"
    "Instagram 公開貼文的摘要流程。每筆內容自動輸出繁體中文摘要、重點、分類、標籤、"
    "AI 編輯觀點與來源資訊，並發布至具搜尋、篩選、排序及詳情頁的 GitHub Pages 網站。"
)

doc.add_heading("3. 資料搜集（靈感、參考、過往經驗）", level=3)
doc.add_paragraph("3-1 過往作品／現有素材：")
doc.add_paragraph("本專案目前為新建專案，工作目錄尚無既有程式或作品內容。")
doc.add_paragraph("3-2 興趣參考：")
add_bullet(
    doc,
    "AI Digest — 每日精選：https://kanibot818.github.io/ai-digest-site/ "
    "（參考卡片列表、分類、搜尋、日期排序、摘要詳情與原文連結）",
)
add_bullet(
    doc,
    "notebooklm-py：https://github.com/teng-lin/notebooklm-py "
    "（用於本機自動上傳影音音源並呼叫 NotebookLM）",
)

doc.add_heading("4. 專案執行規劃", level=3)
doc.add_heading("4-1 專案名稱定錨", level=3)
doc.add_paragraph("專案名稱：AI Digest 個人文章摘要與公開閱讀網站")

doc.add_heading("4-2 產品定位與使用流程", level=3)
doc.add_paragraph("目標使用者：")
add_bullet(doc, "主要使用者為專案執行者本人，用於快速消化每天收集的內容。")
add_bullet(doc, "一般訪客可公開閱讀已發布的摘要，但不能新增或管理內容。")
doc.add_paragraph("核心流程：")
add_numbered(doc, "在本機 Codex 對話中提供一個公開網址。")
add_numbered(doc, "Codex Skill 判斷來源類型，擷取網頁、社群、PDF 或影音內容。")
add_numbered(doc, "文字類內容交由 OpenAI 產生繁體中文摘要。")
add_numbered(
    doc,
    "YouTube 影片下載並轉為音源檔，再透過 notebooklm-py 上傳 NotebookLM 轉錄與摘要。",
)
add_numbered(doc, "系統將結果寫入網站資料並預設發布。")
add_numbered(doc, "使用者可透過 Codex Skill 編輯或下架，再部署至 GitHub Pages。")

doc.add_heading("4-3 本次必做範圍", level=3)
must_have = [
    "支援一般公開且可直接讀取的網頁。",
    "支援 YouTube 公開影片；無字幕時仍須下載影音、轉成音源後交由 NotebookLM 處理。",
    "支援具有可擷取文字內容的 PDF 與論文。",
    "支援 X、Facebook、Instagram 無須登入即可瀏覽的公開單篇貼文。",
    "社群貼文中的圖片文字須納入辨識與摘要內容。",
    "所有來源語言一律產生繁體中文結果。",
    "每筆內容包含：一段短摘要、3～5 個條列重點、分類、標籤、AI 編輯觀點、原文基本資料與連結。",
    "分類由 AI 從預先建立的分類清單中選擇；標籤可由 AI 自由產生。",
    "摘要預設直接發布，並可由本機 Codex Skill 後續編輯或下架。",
    "保存摘要歷史，提供公開列表頁與獨立詳情頁。",
    "公開網站支援日期排序、關鍵字搜尋、分類／標籤篩選。",
    "透過 Codex Skill 將資料與網站變更部署至 GitHub Pages。",
]
for item in must_have:
    add_bullet(doc, item)

doc.add_heading("4-4 本次先不做", level=3)
not_now = [
    "不處理付費牆、需登入或受反爬蟲限制的網頁；失敗時清楚提示原因。",
    "不支援掃描型 PDF 的 OCR，只處理本身具有可擷取文字的 PDF。",
    "不處理私人社群內容、完整討論串或非單篇貼文。",
    "不建立網站管理後台、帳號系統或管理密碼；管理操作全部在本機完成。",
    "不在 GitHub Pages 儲存 OpenAI 金鑰、Google／NotebookLM 驗證資料或 GitHub Token。",
    "Codex Skill 的詳細指令、參數與操作語法留待實作階段另行討論。",
]
for item in not_now:
    add_bullet(doc, item)

doc.add_heading("4-5 專案使用技術（暫定）", level=3)
technology = [
    ("公開網站", "GitHub Pages；靜態前端呈現摘要列表與詳情。"),
    ("本機編排", "Codex Skill；負責來源判斷、內容處理、資料更新與部署。"),
    ("文字摘要", "OpenAI API；處理網頁、社群貼文及文字型 PDF／論文。"),
    ("影音摘要", "影音下載／轉檔工具＋notebooklm-py＋NotebookLM。"),
    ("資料保存", "以適合靜態網站讀取的結構化資料保存，實作階段確認格式。"),
    ("版本與部署", "Git／GitHub；由本機 Codex Skill 執行部署流程。"),
]
tech_table = doc.add_table(rows=1, cols=2)
set_table_borders(tech_table)
set_cell_text(tech_table.rows[0].cells[0], "項目", True)
set_cell_text(tech_table.rows[0].cells[1], "技術／用途", True)
for cell in tech_table.rows[0].cells:
    set_cell_shading(cell, "D9EAD3")
for name, detail in technology:
    cells = tech_table.add_row().cells
    set_cell_text(cells[0], name, True)
    set_cell_text(cells[1], detail)

doc.add_heading("4-6 例外與風險處理", level=3)
risks = [
    "來源無法讀取時不得產生看似成功的空摘要，需顯示可理解的失敗原因。",
    "notebooklm-py 為非官方整合，可能因 Google 內部 API 改動或限流而失效；第一版接受此風險，失敗時清楚提示並允許修復後重試。",
    "YouTube 影音轉檔、長影片處理與 NotebookLM 回應可能耗時，流程需呈現處理中、成功與失敗狀態。",
    "API 金鑰、登入 Cookie 與部署憑證只保存在本機安全環境，不可提交至公開儲存庫。",
    "公開發布前應保留來源連結與基本資料，讓讀者可回到原文核對。",
]
for item in risks:
    add_bullet(doc, item)

doc.add_heading("4-7 完成定義與驗收標準", level=3)
acceptance = [
    "以至少一個實際範例分別驗證：一般網頁、YouTube、文字型 PDF／論文、X、Facebook、Instagram，共七種來源。",
    "七種測試來源都能輸出繁體中文短摘要、3～5 個重點、既有分類、自由標籤、AI 編輯觀點、來源資料與原文連結；不可讀來源則顯示明確錯誤。",
    "YouTube 測試須包含一支沒有可用字幕的公開影片，完成影音下載、音源轉換、NotebookLM 處理與結果保存。",
    "公開網站能正確顯示列表與詳情，並完成日期排序、關鍵字搜尋及分類／標籤篩選。",
    "使用 Codex Skill 完成一次從網址輸入、摘要、保存到 GitHub Pages 更新的端到端流程。",
    "摘要發布後可從本機流程完成至少一次編輯及一次下架，且網站結果同步正確。",
    "公開儲存庫與瀏覽器端不得出現任何 API 金鑰、NotebookLM 驗證資料或部署憑證。",
]
for item in acceptance:
    add_bullet(doc, item)

doc.add_heading("4-8 專案時間規劃", level=3)
doc.add_paragraph(
    "專案期程共四週，自 2026/07/31 起至 2026/08/27 止，不包含企劃當日 2026/07/30。"
)

schedule = [
    (
        "07/31–08/06",
        "第1週：需求定稿與資料模型",
        "確認分類清單、摘要欄位、靜態網站資料格式；建立專案骨架與 GitHub Pages 基礎部署。",
        "尚未開始",
    ),
    (
        "08/07–08/13",
        "第2週：文字來源摘要管線",
        "完成一般網頁、文字型 PDF／論文、X、Facebook、Instagram 公開貼文的擷取、圖片文字辨識與 OpenAI 摘要。",
        "尚未開始",
    ),
    (
        "08/14–08/20",
        "第3週：YouTube 與內容管理流程",
        "完成影音下載、音源轉換、notebooklm-py 串接、摘要保存，以及本機編輯與下架流程。",
        "尚未開始",
    ),
    (
        "08/21–08/27",
        "第4週：公開網站、整合測試與部署",
        "完成列表、詳情、搜尋、排序、分類／標籤篩選；執行七類來源驗收、安全檢查與 GitHub Pages 正式部署。",
        "尚未開始",
    ),
]
table = doc.add_table(rows=1, cols=4)
set_table_borders(table)
headers = ["執行時程", "階段", "專案執行目標", "完成狀況"]
for idx, header in enumerate(headers):
    set_cell_text(table.rows[0].cells[idx], header, True)
    set_cell_shading(table.rows[0].cells[idx], "D9EAD3")
set_repeat_table_header(table.rows[0])
for period, phase, goal, status in schedule:
    cells = table.add_row().cells
    for idx, value in enumerate((period, phase, goal, status)):
        set_cell_text(cells[idx], value, bold=(idx == 1))

doc.add_heading("5. 預期交付成果", level=3)
deliverables = [
    "可公開瀏覽的 GitHub Pages 摘要網站。",
    "支援七類來源的本機摘要與發布流程。",
    "結構化摘要資料及範例內容。",
    "Codex Skill 與操作說明；詳細指令設計於實作階段確認。",
    "來源支援、錯誤處理、部署及敏感資料保護的驗收紀錄。",
]
for item in deliverables:
    add_bullet(doc, item)

# Consistent Traditional Chinese typography.
for paragraph in doc.paragraphs:
    paragraph.paragraph_format.space_after = Pt(6)
    for run in paragraph.runs:
        run.font.name = "Microsoft JhengHei"
        run._element.get_or_add_rPr().rFonts.set(
            qn("w:eastAsia"), "Microsoft JhengHei"
        )
        if run.font.size is None:
            run.font.size = Pt(11)

for section in doc.sections:
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

doc.save(OUTPUT)
print(OUTPUT)
