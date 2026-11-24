# 部署與日常操作

## 私有儲存庫與版本

建議私有 repo，main 設保護規則並要求 CI 成功。開發走短期分支與 PR，首個部署準備版本標為 v0.4.0。功能使用次版本，規則修復使用修補版本。Repo 只含程式、合成樣本、測試、設定範例、部署及驗收文件。

| 路徑 | 用途 |
|---|---|
| job_agent/、main.py | 投遞資料比對、核准、文件及平台 |
| tests/、examples/ | 測試與固定合成資料 |
| config/、.env.example | 空白審核範例與環境變數 |
| scripts/ | 檔案及憑證檢查、發行封裝 |
| .github/workflows/ci.yml | Push、PR 及手動 Dry Run 測試 |
| private/ | 本機私有資料，透過 ignore 排除 |

CI 只使用合成資料和本機 Chromium，沒有服務金鑰、正式資料、外部招聘測試或排程。CI 僅有 contents:read，checkout 不保留 token。上線前確認組織的第三方 Action 版本政策。檔案允許清單與常見金鑰格式檢查無法推斷所有秘密，需搭配 PR 審查。GitHub Private Repository 須先獲使用者核准再建立。

## 安裝與運行

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -v
python main.py --jobs examples/jobs.json --emails examples/emails.json --out /tmp/job-agent-smoke/report.json
```

模板同版輸出另安裝 LibreOffice、原模板所需字型及 PDF 檢閱工具。Linux 使用受管理的 OS/Chromium 信任存放區。遇未知憑證時維持 TLS 拒絕，向環境管理方核對 CA 與指紋。私有資料留在權限受控的本地資料夾或使用者核准的機密儲存空間。若採憑證路線，以唯讀 token 分開注入。正式更新 token 另行授權，僅在有批准且具現況檢查的互動步驟注入。

## 日常流程與排程整合

1. 每日 Gmail 摘要維持人類閱讀用途。同步時讀既有 Gmail 結果，或在本機手動執行一條唯讀收集流程。若未來排程整合，給收集器唯一擁有者，不從摘要及同步兩邊抓信。Gmail message ID 去重，收集水位只在完整讀取並落盤後前推，短期重疊重查避免漏件。
2. 週一台灣外商職缺搜尋沿用現有排程。匯入其已完成結果，流水線以 run ID 或內容雜湊記錄已處理批次，再用官方職缺 URL / requisition 去重。CI 不執行定期搜尋，也不轉貼或重寄週報。
3. 以 `--evidence-dir private/evidence` 產生比對報告及證據。人工先檢查事件與目前 Notion 狀態，再用私有 review JSON 勾選 fingerprint。讀取得到過期狀態時重新產生提議。遇回應逾時重新讀取；若已等於提議狀態，即視為已套用。正式執行應維持單一寫入者，因 Notion 的讀取加 PATCH 不提供跨客戶端條件交易。
4. 由週報挑選可申請職缺，使用用戶提供的正式履歷與 JD 產生 DOCX/PDF，逐頁查核並保存於 private/。只在已授權操作的獨立會話交給申請網站，網站最終提交一律由使用者執行。

## 人工審核介面

優先沿用 Notion「求職紀錄工作台」。正式整合獲准後，在工作台下新增一個關聯到既有投遞的待審核資料來源，保存指紋、原狀態、提議狀態、Gmail 證據連結、決策、決策人與決策日。正文和附件留在原 Gmail 或私有證據庫。預設視圖只顯示待審核與過期；核准狀態本身不觸發寫入。核准後由單一執行程序重新驗證指紋及現況。尚未核准時以本機 Markdown 及 review JSON 操作。

## 部署前清單

- [x] 合成 CI 命令與本機測試已完成
- [x] 真實 Phase 1 唯讀重跑及證據保存
- [x] 六個公開入口唯讀探測，403 和 TLS 問題有記錄
- [ ] 提供指定 DOCX，三個 JD 配對、DOCX/PDF 正式渲染及事實檢查
- [ ] 受管理 Chromium 信任鏈修復後驗證目標平台的動態表單
- [ ] 核准 GitHub 私有 repo 後建立並核對遠端 CI、分支規則
- [ ] 核准後才連接正式審核介面、寫入權限或調整現有排程

回滾使用上一標籤重新安裝。異常時停用寫入入口並保留證據，先在 Dry Run 重新對帳。已寫入的正式資料依審核紀錄逐筆處理。
