# Job Hunting Agent 驗收報告

2026-11-24，Asia/Taipei。全程 Dry Run。

## Phase 1 真實資料

以 21 筆 Notion 投遞和 99 封 Gmail 郵件重跑。從連接器補讀 8 封先前只有摘要的郵件，全部是 LinkedIn 職缺或社群通知，未改變提議，現有 99 封皆有正文。兩次 CLI 的 JSON 和 Markdown 逐位元一致。新結果為 1 筆變更提議、10 筆人工審核、18 筆無需更新、70 筆略過。

原有 20 筆審核分流如下。

| 結果 | 筆數 | 原因 |
|---|---:|---|
| 無需更新 | 4 | Qualcomm Workday 內部 ID 與既有外部 ID 透過相同職稱對照 |
| 無需更新 | 4 | 可信來源和唯一職稱足以辨識已記錄的投遞 |
| 略過 | 2 | 會議助理通知或個人回信 |
| 保留審核 | 3 | 測驗缺乏唯一 requisition |
| 保留審核 | 3 | 面試缺乏唯一 requisition |
| 保留審核 | 2 | 投遞確認缺少足以辨識的職稱或 ID |
| 保留審核 | 1 | 投遞確認可能對應多筆紀錄 |
| 保留審核 | 1 | 已匹配的招募方附加資料要求，需人工處理 |

測試覆蓋同日事件時間順序、拒絕後較新事件、重新投遞日期、已拒絕、Offer、停止追蹤、核准前不寫、狀態過期及寫入成功但回應遺失後重試。新版寫入前讀取狀態的保護在本機測試使用替身，正式 Notion PATCH 未執行。每筆提議附原始 Gmail URL、訊息 ID、時間和正文 SHA-256，原始正文快照另外保存在私有證據資料夾。

## Phase 2 三筆真實週報職缺

| 職缺 | 分數 | 經歷可對照處 | 驗證 |
|---|---:|---|---|
| Canonical Linux Software Engineer, Next-Gen Silicon | 68.38 | Linux、跨架構 SDK、效能除錯 | 既有週報有官方連結。11/24 重查回傳 503 或逾時 |
| Obsidian Security Agent Security Research Engineer | 67.12 | Agent 整合、系統除錯；OAuth 及安全研究需獨立確認 | 官方職缺 HTTP 200，HTML 有一份表單和兩個檔案欄位 |
| Obsidian Security AI Security Engineer | 65.38 | AI 系統與工程整合；SaaS 安全與資料後端經驗需獨立確認 | 官方職缺 HTTP 200 |

薪資、職涯發展、面試可行性沿用 50 的中性值並標記缺口，技術分數取自原週報。指定 DOCX 不在已提供的工作區、Drive 搜尋或 Gmail 檔名搜尋中，因此未生成三份個人版履歷。替代測試使用合成資料，通過 DOCX/PDF ATS 文字順序一致、來源句保留、PDF 頁數與求職信詞數。正式模板的渲染、頁數及逐項事實查核仍待原檔與模板字型。

## Phase 3 招募平台

| 平台 | 公開頁 HTTP | 驗證範圍 |
|---|---:|---|
| AMD | 403 | 官方職缺入口，網路存取受限 |
| NVIDIA | 200 | Workday 公開入口 |
| Qualcomm | 200 | Eightfold 職缺入口 |
| Google | 200 | 公開搜尋頁，偵測到搜尋表單 |
| Amazon | 200 | 公開入口 |
| Garmin | 403 | 官方入口，網路存取受限 |

六個平台均使用 TLS 預設校驗的唯讀 adapter，包含主機白名單、公開頁特徵與適用的 requisition 擷取。HTTP 200 代表能到達所列入口。動態申請欄位及系統登入內頁尚未驗收。本機 Chromium 的模擬表單流程通過。

curl 與 Python 使用系統 CA 成功驗證環境代理簽發的主機憑證，curl 的 ssl_verify_result 為 0。Chromium 對 Greenhouse 回報 ERR_CERT_AUTHORITY_INVALID。將已由系統信任的環境代理 CA 匯入工作區外的臨時 NSS 資料庫並以 XDG 設定重試，仍未被 Chromium 採用。正式環境應使用正常公有憑證路徑，或透過管理員維護的瀏覽器信任政策配置環境 CA。沒有關閉驗證，也沒有傳送履歷。

## Phase 4

完成私有儲存庫目錄規劃、唯讀 CI、安裝設定、版本及審核流程。遠端 GitHub、CI 線上執行與排程改動均保留到獲准後。見 DEPLOYMENT.md。
