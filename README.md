# Job Hunting Agent

Python 3.12。預設 Dry Run。開發狀態、真實資料覆蓋範圍及限制見 PROJECT_SPEC.md、PROGRESS.md 和 CHANGELOG.md。

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

瀏覽器測試使用系統的 `chromium`。CLI 可用 `--chromium` 指定位置。

## Phase 1

```bash
python main.py --jobs examples/jobs.json --emails examples/emails.json --out private/example.json
python main.py --jobs private/notion.json --emails private/gmail.json --out private/phase1-diff.json
```

Notion 支援既有 connector rows 及官方 API page。Gmail 支援 connector 摘要及已正規化的全文訊息。完整正文須明確標記 `body_complete: true` 並提供 `date`、`subject` 和 `body`。HTML 內容以 `body_html: true` 標記。範例皆為測試資料。

輸出同名 JSON 與 Markdown。人工審核時，將 JSON 的 review 指紋放入私有檔案，值填 `approve` 或 `reject`，重新執行並傳入 `--review` 可檢查決策。CLI 只保存本機審核結果。後續經正式授權才能以 `apply_approved` 和 `NotionReviewGateway` 發送更新。

已有官方 API 唯讀權限時，可設 `NOTION_TOKEN` 和 `GMAIL_ACCESS_TOKEN`，再以 `--notion-data-source-id UUID --gmail-live` 取代快照輸入。舊版 Notion 以 `--notion-database-id` 查詢。憑證由環境注入。

## Phase 2

```bash
python -m job_agent.prepare rank private/weekly.md private/ranked.json
python -m job_agent.prepare docs private/profile.json private/job.json private/jd.txt private/docs
```

週報匯入沿用連接器現有輸出的 Markdown 表格。可用 `--assessments` 指定按 URL 索引的分數，欄位為 technical、career、salary、location、interview。履歷 profile JSON 包含 name、contact，以及由 heading、bullets 組成的 sections。job JSON 包含 company 和 title。JD 傳入英文原文。

將兩個逐頁插槽 `{{RESUME_PAGE_1}}`、`{{RESUME_PAGE_2}}` 加至模板副本後，才使用 `--template FILE`。指定的原始模板仍待檢查。模板模式依賴 LibreOffice。

## Phase 3

```bash
python -m job_agent.application --url https://example.com/jobs/1 --chromium /usr/bin/chromium
python -m job_agent.application --fixture local-form.html --values private/fields.json --chromium /usr/bin/chromium
```

fields JSON 包含 values 與 uploads，兩者以頁面 input ID 為鍵。演練使用本機 HTML 並封鎖網路請求。互動投遞必須另外核准後才使用 `--interactive`，由使用者在畫面上確認並提交。提交後將使用者已確認的日期與證據 URL 傳給 `notion_suggestion` 產生更新建議。

請將快照、履歷、email 附件、投遞收據與完整差異報告保存在 private/。

## 驗收與發行

詳見 ACCEPTANCE.md 與 DEPLOYMENT.md。唯讀檢查招聘入口可執行 `python -m job_agent.platforms`。Phase 1 保存原文證據請加 `--evidence-dir private/evidence`。建立發行包可執行 `python scripts/package_release.py /tmp/job-agent-v0.4.0.zip`。匯入 Git 後使用 `python scripts/validate_repository.py` 檢查暫存區。
