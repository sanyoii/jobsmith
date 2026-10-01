# JobSmith：求職條件查證與投遞憑證最小整合規格

日期：2026-10-01（Asia/Taipei）
狀態：功能實作、隔離自動驗證與正式資料庫備份／遷移完成；真人驗收與發布未執行。

使用者後續「依照建議處理至完成」已授權本批功能與隔離 schema 演練。第 1–11 節保留原規格階段脈絡，其中「本輪未實作／待執行」描述的是規格階段；實作結果見第 12 節，正式資料庫啟用結果與目前限制以第 13 節為準。

## 1. 目標、架構與範圍

讓使用者看得出「哪些求職條件已查過、依據在哪」，並把投遞結果和實際憑證保存在 JobSmith。沿用 FastAPI、Pydantic、SQLite、React/Vite 與 Windows 包裝；JobSmith 是唯一紀錄來源。

第一批只做手動記錄、保存、顯示與檢核。查證不足不阻止製作投遞包；核可文件不代表已投遞。既有搜尋、匹配分數、生成流程、AI 後端與文件匯出保持相容。

不包含：搬上游程式碼、另一套工作台、雙向同步、WebMCP、郵件連接、自動網站查證、自動投遞、多人協作、地圖、個人事實庫或 Critic 調整。後兩項是後續獨立範圍，不藏進第一批。上游 README 與 package.json 的授權標示不一致；此規格參考設計，不複製實作。

## 2. 已核對的接點

本機基準 HEAD：4340e9ca5979092e0d534036d5607197d121db99，加既有未提交修改。以下是原始碼證據，未執行功能測試。

| 現有落點 | 現況 | 第一批處理 |
|---|---|---|
| app/models.py：JobPosting、JobMatch | URL、地點、薪資、工作模式及匹配分數 | 沿用；不把 remote 推定為台灣可聘僱 |
| app/store/searches.py | 搜尋以 JSON 整包保存 | 保留搜尋快照；查證另有唯一來源 |
| frontend/src/components/jobs/JobList.tsx | 搜尋及搜尋歷史共用列表 | 共用條件摘要與編輯入口 |
| JobSearchView.tsx、SearchHistoryView.tsx | onPick 只傳 JD 與 Profile | 增加可選職缺來源資訊 |
| frontend/src/App.tsx、views/PipelineView.tsx | seed → /api/run | 傳遞可選 job_url，舊呼叫仍可用 |
| app/server.py：RunBody、run | 建立背景投遞包 | 保存來源關聯；不加入 LLM prompt |
| app/store/db.py、history.py | approved、outcome_status、outcome_note | 保留欄位與舊值，新增事件後投影目前結果 |
| app/server.py：history_outcome | applied/interviewing/offer/rejected/ghosted/null | 保留端點與值域，擴充可選憑證 |
| frontend/src/views/HistoryView.tsx | 結果選單及備註 | 變更先暫存在表單，後端成功才更新畫面 |
| app/server.py：privacy_data_delete | 清除既有個人資料 | 新資料必須納入既有清除流程 |

實作前重驗接點及 diff。目前已有 8 個修改檔、.claude/、.claude-flow/ 與兩個未追蹤來源檔；不覆蓋、不回退、不混入本批提交。這份規格不替既有修改背書。

## 3. 同一情境的前後差異

| 情境 | 現有行為 | 預期行為，尚未實作 |
|---|---|---|
| Remote 沒有台灣聘僱說明 | 工作模式與匹配分數 | 另顯示台灣聘僱待確認，可記來源與時間 |
| 查到必須輪班 | 資訊留在原文或聊天 | 顯示輪班／待命不符合，展開看依據 |
| 核可文件 | approved 更新 | 文件核可；投遞結果不因此改變 |
| 選擇已投遞 | 直接更新 outcome_status | 本人確認成功頁、申請編號或確認信摘要後保存 |
| 舊 applied 沒憑證 | 已投遞 | 原值保留，另標舊紀錄憑證未核對 |
| 保存失敗 | setOutcome 未檢查 HTTP 結果 | 保留原狀態及表單，顯示錯誤、可重試 |

## 4. 求職條件契約（擬新增）

固定五項：taiwan_eligibility（台灣聘僱）、work_mode（工作方式）、schedule（輪班／待命）、salary（薪資）、employment_type（聘僱形式）。pass/fail 表示符合／不符合「本次記錄的要求」，不是一般好壞評分。

| 欄位 | 契約 |
|---|---|
| criterion | 上述固定值之一 |
| requirement | 使用者本次希望的條件，1–500 字，避免換目標後沿用舊判斷 |
| value | pass / fail / unknown |
| evidence | 依據原文或摘要，最多 3,000 字；pass/fail 必填，unknown 可空 |
| source_url | HTTPS 來源，最多 2,048 字；pass/fail 必填，unknown 可空 |
| checked_at | 含時區；pass/fail 必填；不得晚於伺服器時間 5 分鐘；unknown 可空 |
| saved_at | 伺服器 UTC 時間，不接受客戶端覆寫 |

source_url 只保存及安全呈現，不觸發抓取；拒絕內含帳密、非 HTTPS 協定與控制字元。不把任意 URL 標成官方已驗證。連結另開頁使用 noreferrer/noopener，所有摘要以純文字呈現。

採 7 天提醒期限作為可調整的產品預設：超過期限標查證已過期，保留原 value 與依據，不偽造新 checked_at，不自動改 fail。無資料或無日期顯示待確認。摘要優先順序：有未過期 fail → 有條件不符；否則有缺資料、unknown 或過期 → 仍有條件待確認；全部五項有未過期 pass → 五項均有符合依據。只對照已記錄的 requirement，不代表整體適任或錄取機率。

職缺 key 第一批只去 fragment、正規化 scheme/host，保留 path、query 與大小寫敏感識別。不同 URL 不自動合併，不能通用刪除 ref/source。同 URL 的某項更新只取代目前該項查證，不改投遞事件。

job_url 沿 JobList → onPick → App seed → PipelineView → RunBody → packages 保存。手動 JD、舊包無 URL 顯示未連結職缺來源，允許本人補上；不從公司名稱或生成文字猜 URL。查證在搜尋歷史標示為「目前查證」，不冒充搜尋當時已知資料。

## 5. 投遞事件與憑證契約（擬新增）

保留 outcome_status、outcome_note。新增事件為本批啟用後狀態變更來源，欄位：event_id、package_id、idempotency_key、status（沿用現有值域及 null）、occurred_at、recorded_at、evidence_kind、evidence_text、可選 source_url/reference、confirmed_by_user，以及可選 correction/correction_reason。

event_id、recorded_at 由伺服器產生；idempotency_key 為每次表單提交新產生的 UUID，重試沿用。本人確認由使用者明確勾選，不預選、不由 AI 推定。第一批系統沒有本人身份驗證，不把勾選欄位說成身份保證。

| 結果 | 保存要求 |
|---|---|
| applied | success_page/application_reference/confirmation_email；非空摘要、本人確認；application_reference 另需非空 reference |
| interviewing/offer/rejected | portal/email/manual；非空摘要、本人確認，manual 可記實際電話通知 |
| ghosted | manual；最後聯繫日期或觀察說明；只表示本人目前判斷 |
| null | 更正回未投遞，需更正原因及本人確認；保留舊事件 |

摘要 1–3,000 字、reference 1–200 字。事件時間含時區，不在未來超過 5 分鐘。郵件與申請編號不強制公開 URL；不收附件、完整郵件、登入 cookie 或 token。憑證表示本人記錄並確認，系統未自動驗真。

按 occurred_at 排序。早於目前有效事件回 409；相同時間且不同結果需更正。一般前進 applied → interviewing → offer；rejected/ghosted 可從活動狀態設定。倒退、終態變更或清除須 correction=true 及非空原因。明確更正以本次記錄時間作為新投影基準，另保留被更正事件 ID，避免下一筆事件因舊的 occurred_at 誤覆蓋更正。

同 package 的新增事件、outcome_status/outcome_updated_at/outcome_note 投影在同一 SQLite 交易。失敗全部回滾。只在 payload 明確帶 note 時更新備註。相同 key 相同 payload 回原事件；相同 key 不同 payload 回 409。不存在 package 回 404，不產生孤兒事件。新客戶端變更同時帶 expected_event_id（無事件為 null），以交易內比較防止並行表單覆蓋；不一致回 409。

舊狀態不回填成功事件或本人確認；沒有事件時第一份有效憑證建立起點。舊 client 原 outcome payload 仍可更新人工狀態，但需留下未驗證人工事件（伺服器生成 key），使原已確認憑證不替新結果背書。只改 note 且 status 與目前相同的舊請求維持備註編輯，不取消既有憑證；新 UI 不走無憑證狀態變更相容路徑。

## 6. 擬新增儲存與 API

需要 schema 變更；明確授權後才能實作或執行 migration。本輪不操作 SQLite。

packages 增 nullable job_url；新增 job_verifications（職缺 key＋criterion 唯一鍵，保存目前查證 JSON），application_events（package 關聯、事件 JSON、唯一 idempotency key）。不複製 searches、不另建 applications 帳本。沿既有共用連線及 LOCK 管理交易。

| 方法/路徑，全部擬議 | 契約 |
|---|---|
| POST /api/job-verifications/query | {job_urls:[...]}，上限 100；回目前紀錄與摘要；不寫入、不抓網站 |
| PUT /api/job-verifications | {job_url,check}；只更新該 criterion，回保存值與摘要 |
| PATCH /api/history/{pid}/outcome | 擴充既有 body，可選 evidence、idempotency_key、occurred_at、expected_event_id、correction、correction_reason；新舊格式分別驗證 |
| GET /api/history/{pid}/events | 分頁預設 50、上限 100，回事件與 next_cursor |
| PATCH /api/history/{pid}/job-source | {job_url}，本人補來源，不改 JD；null 解連結，不刪查證 |

格式錯誤 422、缺 package 404、key/順序/並行衝突 409、內部錯誤 500。診斷與錯誤日誌不印憑證全文。RunBody 增可選 job_url，缺省 null；history 增 job_url、current_event_id、evidence_status（legacy_unverified/user_confirmed/unverified），保留舊欄位。user_confirmed 只在目前狀態由本人確認事件投影時顯示，不能因某個過去事件存在就顯示。

刪 package 同交易刪其事件。單一搜尋或包刪除不刪 URL 查證，因為其他紀錄可能使用。清除個資須清所有查證、事件與畫面快取。延伸既有使用者清除動作，不能為驗證刪真實資料。

## 7. 畫面與失敗處理

職缺卡增加一行摘要及記錄查證入口，五項表單展開要求、依據、來源、日期。不新增主選單。包詳情顯示來源與目前查證，允許補來源。HistoryView 結果變更以表單明確保存，旁邊顯示憑證及事件時間。

保存中防雙擊；成功前不更新狀態。非 2xx、網路中斷、422/409 保留表單與原狀態，顯示錯誤；重試同 key。讀取失敗顯示查證資料讀取失敗，不能當未查證或符合。若宿主既有邊界回 401/403，正常呈現；本批不新增登入或權限系統。文字與互動需鍵盤可用、表單有標籤，不能只用顏色區分狀態。

## 8. 實作責任與順序

後續單一寫入者，本輪沒有代理委派。以下是實作範圍，不是本輪修改清單。

**A：來源與條件查證。** app/models.py、app/store/db.py、app/store/history.py、app/server.py；新增 app/store/job_verifications.py；frontend/src/types.ts、App.tsx、views/JobSearchView.tsx、SearchHistoryView.tsx、PipelineView.tsx、components/jobs/JobList.tsx；新增 components/jobs/JobVerificationPanel.tsx；tests/test_history.py、test_server.py，新增 tests/test_job_verifications.py。完成點：保存→刷新→搜尋歷史與包詳情讀同 URL 查證；舊生成呼叫保持相容。無 schema 授權或無法保留髒檔即停。

**B：投遞事件。** app/store/db.py、history.py、app/server.py、frontend/src/views/HistoryView.tsx；新增 app/store/application_events.py；tests/test_history.py、test_server.py，新增 tests/test_application_events.py。完成點：事件及投影交易一致，重試/順序/並行防護通過後才接 UI；舊 client 不冒充確認結果。

**C：整合與清除。** 上述必要檔、tests/test_security_regressions.py、docs/PRIVACY.md。完成點：來源傳遞、錯誤 UI、舊資料及個資清除全通；隱私文件只說明新儲存。

不改 app/sources/*、app/agents/*、app/llm*、app/graph.py、依賴、桌面啟動器或發布設定。接點漂移、scope 擴大或 schema 授權不足先停，不邊做邊加入功能。A/B/C 各自檢查，再跑整合 checkpoint；完成文件不代表通過功能驗收。

## 9. 待執行驗收

| ID | 輸入/動作 | 預期 |
|---|---|---|
| V01 | remote 無台灣聘僱依據 | 待確認，fit_score 不變 |
| V02 | pass 缺來源或摘要 | 422、不寫入、保留表單 |
| V03 | unknown 沒憑證 | 可保存，不補假日期 |
| V04 | 查證 8 天 | 原值保存，顯示過期及待確認 |
| V05 | 保存某 URL，刷新搜尋/歷史 | 同一查證；不同 query 不合併 |
| V06 | 選職缺→生成→重啟 | job_url 留在包；手動 JD 舊請求成功 |
| V07 | 更換 requirement | 新要求與新判斷成對保存 |
| E01 | 文件核可 | approved 更新，outcome 不變 |
| E02 | 新 applied 缺憑證或確認 | 422，事件與投影都不寫 |
| E03 | 合法申請編號及本人確認 | 一次交易，重啟可讀 |
| E04 | 同 key 同 payload 重試 | 同事件，不新增 |
| E05 | 同 key 不同 payload | 409，原值保持 |
| E06 | 投影失敗 | 事件亦回滾 |
| E07 | 舊 applied 無事件 | 原值保留、憑證未核對 |
| E08 | 舊 client 改狀態/備註 | 狀態留未驗證事件；同狀態改 note 不取消憑證；未帶 note 不洗掉 |
| E09 | 較早、倒退、終態衝突 | 409，明確更正原因才保存 |
| E10 | 更正回未投遞 | null，舊憑證事件可回看 |
| E11 | 缺 package/過期 expected_event_id | 404/409，不寫半筆 |
| I01 | HTML 或危險 URL | 純文字、安全連結、不執行與抓取 |
| I02 | 500/網路斷線 | 原狀態及表單保留，日誌不洩憑證 |
| I03 | 測試 DB 刪包/清個資 | 事件清掉；清個資亦清查證與快取 |
| I04 | 搜尋、生成、核可、匯出 | 相容，不增加 AI 呼叫或外部投遞 |

## 10. 後續驗證、授權、回復與交接

實作後先在隔離測試資料庫跑下列指令；新增測試檔只有實作後才存在，本輪沒有執行：

~~~bash
py -3 -m pytest tests/test_job_verifications.py tests/test_application_events.py tests/test_history.py tests/test_server.py tests/test_security_regressions.py --basetemp=.pytest-run-tmp
cd frontend
npm run lint
npm run build
~~~

預期 exit 0。再用測試資料原生操作 V05/V06/E03/E10/I02/I03，刷新及程序重啟後回讀，做鍵盤及失敗路徑檢查。最後由本人閱讀畫面文字與實際流程；模型測試不替代真人驗收。只因新變更、失敗或未解疑慮才擴大測試。

migration 前須取得涵蓋 schema 的授權，對目標 DB 做一致性備份並驗可讀；不能只複製正在寫入的 DB 檔假裝完整備份。先用隔離舊資料複本演練，缺省 job_url=null、舊 outcome 原值保留、重複 migration 不重加欄位。此次不執行備份、migration 或資料刪除。

回復保留新增事件/查證，停用新增畫面/API、只回復本批程式。新增 nullable 欄及表不破壞性刪除；若需覆蓋舊 DB，先匯出新增資料並取得覆蓋授權，說明會失去備份後資料。不 git reset --hard 或整庫回退其他修改。

交接證據：最終 diff、測試 stdout/exit code、migration 舊資料演練、原生操作與未驗項。由主實作者重跑必要檢查；不自動委派或把獨立模型 review 當本人驗收。

後續需另取得授權：功能實作及 schema/migration、真實資料修改、刪除/覆蓋、外部服務、Git 提交/推送及 exe 打包發布。本輪完成條件：本文件落檔、接點可追溯、契約/相容性/驗收/限制完整，未改程式或 DB。

## 11. 上游參考與證據邊界

上一輪取回版本 6577fab8f20aeaf6a265a7a00223561f782c17cc。本輪未重抓、未安裝或執行上游；這些是固定版本設計參考，不是可搬碼授權、互通證明或 current runtime PASS。

- [條件、事實與事件順序](https://github.com/Cornelius-Chen/AI-Career-Workbench/blob/6577fab8f20aeaf6a265a7a00223561f782c17cc/lib/domain.ts)
- [查證與事件 API](https://github.com/Cornelius-Chen/AI-Career-Workbench/blob/6577fab8f20aeaf6a265a7a00223561f782c17cc/app/api/workspace/route.ts)
- [上游資料模型](https://github.com/Cornelius-Chen/AI-Career-Workbench/blob/6577fab8f20aeaf6a265a7a00223561f782c17cc/db/schema.ts)
- [README 許可](https://github.com/Cornelius-Chen/AI-Career-Workbench/blob/6577fab8f20aeaf6a265a7a00223561f782c17cc/README.md) 與 [package.json](https://github.com/Cornelius-Chen/AI-Career-Workbench/blob/6577fab8f20aeaf6a265a7a00223561f782c17cc/package.json)


## 12. 實作交付與驗證結果（2026-10-01）

本批程式完成，沿用 JobSmith 架構自行實作；未搬入或執行 AI-Career-Workbench 程式。第 12 節記錄實作驗證階段；正式資料庫於使用者再次授權後完成備份與遷移，詳見第 13 節。未提交／推送、未打包或發布。

### 已交付行為與檔案

| 使用位置／責任 | 結果／來源 |
|---|---|
| 搜尋卡、搜尋歷史與包詳情 | 共用五項手動查證：台灣聘僱、工作方式、輪班／待命、薪資、聘僱形式；來源、本人要求、依據及時間一起保存，七天過期提醒；[畫面](../../frontend/src/components/jobs/JobVerificationPanel.tsx)、[資料檢核](../../app/store/job_verifications.py) |
| 選職缺、生成、重開包 | job_url 經 seed → RunBody → packages 保存；本人也能補來源；[PipelineView](../../frontend/src/views/PipelineView.tsx)、[history](../../app/store/history.py)、[server](../../app/server.py) |
| 投遞結果 | 需憑證摘要與本人確認；申請編號類型必填編號；更正保留事件。投影與事件同交易；同 key 重試、並行及順序衝突檢核；[事件 store](../../app/store/application_events.py)、[HistoryView](../../frontend/src/views/HistoryView.tsx) |
| 舊資料及個資 | 舊結果保留並標憑證未核對；舊 client 相容；刪包連帶刪事件、清除個資亦清查證；[資料庫](../../app/store/db.py)、[隱私說明](../PRIVACY.md) |
| 可重跑驗證 | [條件測試](../../tests/test_job_verifications.py)、[事件測試](../../tests/test_application_events.py) |

實例：隔離職缺「QA 測試職缺」記錄台灣聘僱符合後，摘要仍是「仍有條件待確認」，因為另外四項尚未查證。保存申請編號 TEST-UI-001 與本人確認後，顯示「已投遞。本人已確認憑證；系統未自動驗真」；模擬保存面試邀約回 500，仍保留已投遞及草稿。

### 本場實際執行

| 檢查 | 結果與邊界 |
|---|---|
| 完整 pytest | 334 passed、2 deselected、1 warning，8.65s，exit 0；2 項 live API 測試依既有設定排除；warning 為既有 Starlette httpx deprecation |
| 新規格的 store/API | 缺憑證 422、URL 安全、未知及過期、不同 query 不合併、事件交易回滾、idempotency、並行 409、明確更正、分頁、刪除及個資清除均有隔離測試 |
| 舊 SQLite 演練 | 既有 DB 不自動加本批 schema；未遷移 API 回 503；顯式遷移重跑安全，舊 outcome/note 保留；關閉再重開隔離檔後 job_url、查證與本人確認事件可讀 |
| 前端 lint | npm run lint，exit 0 |
| 前端 build | npm run build，exit 0；TypeScript 與 Vite 編譯成功 |
| 自動化 UI | 127.0.0.1:8767，兩個記憶體 DB、虛構履歷／職缺，無頭 Chromium；實際操作保存查證、保存憑證、刷新讀回、事件顯示、注入 HTTP 500 保留草稿及原狀態，全部 PASS |
| 並行 HTTP 回歸 | 收尾發現新 schema 檢查未鎖定共用 SQLite 連線，造成偶發 IndexError；改用 RLock 並在 schema 查詢取得鎖，補保有鎖及讀寫並行測試；修正後 8 執行緒、120 次實際 HTTP 查詢全部 200，畫面完整流程再次通過 |
| 手機畫面 | 390×844 viewport 無水平溢出；未做真人可讀性或 screen reader 驗收 |
| Git 檢查 | git diff --check 通過；重疊 server.py 與 JobSearchView.tsx 對本輪修改前副本比較，差異只涉及本批接點，既有來源篩選修改保留 |

執行方式（本機已存在 .venv 與前端依賴，未新增套件）：

~~~bash
.venv/Scripts/python.exe -m pytest tests -q --basetemp="<全新隔離暫存目錄>" -p no:cacheprovider
cd frontend
npm run lint
npm run build
~~~

Windows 再跑測試須選全新的暫存目錄，避免 pytest 先清理既有 basetemp。重用 .pytest-run-tmp 的一次補驗因清理權限產生 4 個 setup errors（329 passed），換新隔離目錄並補並行回歸後完整 334 項通過；未刪除或放寬既有目錄權限。

### 尚未驗證／啟用

本批 schema 只在新空 DB 初始化或顯式 migrate_evidence(conn) 時建立；既有未遷移資料庫的新 API 回 503，不靜默更動 schema。本工作區正式資料庫現已完成授權遷移，見第 13 節。

本次沒有真正呼叫 AI 生成、外部求職網站或提交申請，也沒有登入使用者瀏覽器、網路斷線 UI、完整鍵盤／輔助技術測試及真人流程驗收。官方 CUA 入口因本機含方括號路徑的權限解析而無法啟動，本次 UI 證據來自隔離無頭 Chromium，不宣稱原生 Chrome 驗收。

既有工作樹仍保留使用者其他來源與測試修改；本批不 stage、commit、push，不修改全域設定或 Memory。


## 13. 正式資料庫啟用完成（2026-10-01）

使用者再次回覆「依照建議處理至完成」，授權上輪唯一建議：備份並遷移 JobSmith 正式資料庫。核對啟動器、環境中的資料庫設定與本機程序後，目標為本工作區 [data/app.sqlite](../../data/app.sqlite)；未發現正在執行的 JobSmith／Python 程序。未操作其他 exe 的 JobsmithData 或其他工作區。

### 備份、演練及資料保存

- SQLite backup API 一致性備份：[app.sqlite.pre-evidence-20261001T102239Z.bak](../../data/app.sqlite.pre-evidence-20261001T102239Z.bak)。已確認備份可讀、integrity_check=ok，並由現有 gitignore 排除。
- 先把備份複製至全新暫存 SQLite，演練 migrate_evidence 兩次，完整性正常、舊欄位與逐列資料一致。
- 正式遷移前取得 BEGIN IMMEDIATE 寫入鎖，再次比對備份與原 DB 相同後新增 packages.job_url、job_verifications、application_events 及事件索引。沒有更改既有紀錄。
- 遷移前後 packages=0、searches=4、resume_checks=0、user_memory=0；所有既有欄位與逐列資料完全一致。兩張新表均為空，沒有插入測試查證或假投遞。
- 關閉再開啟 DB：schema_ready=true、integrity_check=ok。

### 實際 runtime 驗證與限制

以目前程式及此正式 DB 啟動 FastAPI TestClient；diagnostics 回傳目標路徑一致。查證 query 新 API、history、searches 與前端首頁全部 HTTP 200；再比對備份中的既有資料完全一致。測試未呼叫 AI、抓取網站或提交申請。既有 Starlette httpx deprecation warning 保留，未因此安裝依賴。

資料庫已可供目前工作區的 run.bat／原始碼啟動器使用。本次沒有留下常駐服務，也沒有更新獨立 exe、Git 提交、推送或發布；真人閱讀與實際求職流程驗收仍未執行。

回復來源為上列遷移前備份；不要在服務寫入時直接覆蓋原 DB。若日後需要回復，先保存新增的查證與事件，確認關閉所有 DB 寫入者後再另行授權回復，避免丟失備份之後的資料。


## 14. QA 履歷搜尋偏向後端的修正（2026-10-01）

使用者提供 William-Lu-General-QA-Resume.pdf 及搜尋畫面。實際 PDF 標題為 Senior QA Engineer，內容以測試設計、QA、自動化及 RCA 為主，Python／API 是測試工具與驗證範圍。未將原始 PDF、個資或履歷全文複製到 repo。

以附件執行原本備援程式，preferred_roles 得到 AI 工程師、後端工程師，搜尋詞得到 AI 工程師、後端工程師、Python 後端，與截圖一致。備援職務規則缺 QA；英文 marker 用子字串比對，maintained／trained 中的 ai 被當 AI、API 驗證被當後端背景。關鍵字提示範例亦偏 AI／後端。未取得當次完整模型回覆，因此不宣稱已確認那次線上搜尋是否確實觸發備援。

修正 [resume_eval.py](../../app/agents/resume_eval.py) 與 [job_search.py](../../app/agents/job_search.py)：履歷主要 QA 職稱優先，工具不能直接推定轉職；英文 marker 改完整詞邊界；QA Profile 的備援搜尋沿 QA 職務，並過濾明顯非 QA 的模型搜尋詞。保留明示混合求職目標、使用者自訂關鍵字及正常後端履歷行為。共用方法是先看主要職稱／明示目標，再用工具細化搜尋，避免用技能取代職務。

新增 [履歷回歸](../../tests/test_resume_eval.py) 及 [搜尋回歸](../../tests/test_job_search.py)。本輪完整 pytest 341 passed、2 deselected、1 warning，5.72s，exit 0；git diff --check 通過。只改後端及測試，未重建前端。

用使用者原始 PDF 上傳至隔離 TestClient，刻意模擬履歷解析失敗及模型回錯誤 AI／後端詞：角色為 QA 工程師、測試工程師、自動化測試工程師；搜尋詞為 manual test、QA 工程師、測試工程師、自動化測試工程師。未呼叫真實 AI、外部搜尋或寫入正式 DB。

目前常駐 run.bat 沒有自動 reload；仍在運行的舊服務需停止當次搜尋、關閉並重新啟動，再重新上傳履歷搜尋，才會使用新程式。沒有自行中斷使用者的當次搜尋、清除既有紀錄或提交／推送。本次控制測試不替代實際模型與求職網站的再次搜尋。


## 15. 各站搜尋語言與 QA 職務校正完成（2026-10-01）

本輪授權為執行前輪建議：職務與工具分開、依來源規劃中英搜尋詞、驗證來源搜尋行為、區分失敗與零結果。程式及有限實測已完成；真實 AI 全流程、使用者原生 Chrome 與真人適配判讀尚未驗證。正式資料庫未寫入本輪測試資料。

### 改後行為與方法

- [query_plan.py](../../app/sources/query_plan.py) 用有限 QA 職務別名規劃搜尋：104／Yourator／Cake 中英並用；LinkedIn 與其餘海外來源優先英文。未知詞保留原文，不憑空翻譯；使用者自訂詞保持逐字且優先。每來源最多五組，先涵蓋不同 QA 職務再補同義詞，避免單一職務吃光預算。
- 同一 QA 履歷的 QA 工程師、測試工程師、自動化測試工程師，海外搜尋轉為 QA Engineer、Software Test Engineer、QA Automation Engineer 等。原本所有來源共用中文詞；現在各來源有自己的查詢清單。這些是搜尋別名，不新增求職目標。
- DeFi Jobs 原本 QA Engineer 可因任一 engineer token 命中 Backend Engineer；現在完整片語的所有詞必須在職稱中命中，全部片語抓取一次後比對，避免重複下載與公司名稱誤命中。
- Web3.career 初次實測發現舊 ?search= URL 回相同非 QA 列表；QA 詞改走網站既有 quality-assurance-jobs 分類，衍生 QA 別名合併為一次分類查詢。其他職務的舊搜尋路由語意尚未驗證，不宣稱已修復全部職務。
- [job_search.py](../../app/agents/job_search.py) 加入純 QA 目標的職務檢查：Backend QA Engineer 保留；Backend Engineer 的共同 Python／API 工具不能取得高適配分；資訊不足或硬體／滲透等不確定職務標記「職務待確認」。明確非 QA 分數上限 30、待確認上限 59，是保守排序規則，並非校準過的就業成功機率。混合明示求職目標沿原行為。
- [JobSearchView.tsx](../../frontend/src/views/JobSearchView.tsx) 可展開各站實際搜尋詞，來源數量按 URL 去重，查詢計畫存入搜尋紀錄 payload。無匹配、條件過濾後零、部分失敗、全部失敗分開顯示；正常零結果不載入範例。全部請求失敗仍沿既有範例備援，明確標示為範例資料。

共用判準：先確認來源確實接受查詢、再談語言效果；職務判斷與技能重疊分開；來源失敗不當作市場零職缺；原文自訂搜尋詞不偷偷改意圖。回歸放在 [test_query_plan.py](../../tests/test_query_plan.py) 與 [test_server.py](../../tests/test_server.py)。

### 有限真實來源比較

完整收據：[中英搜尋比較 JSON](2026-10-01-qa-search-language-comparison.json)。僅送 QA 工程師／QA Engineer 兩組一般查詢，未送履歷或個資。十來源合計初測 19 次請求，DeFi 共用一次；Web3 修正後另一次，共 20 次。每查詢一頁、最多 15 筆，結果為單次快照，不能估算整站召回率。

| 來源 | 本次可確認的結果 | 判讀限制 |
| --- | --- | --- |
| 104 | 英文查詢獨有 12 筆，其中 11 筆由職稱規則辨識為 QA | 中英都值得保留，並非只需中文；尚未逐筆真人查證 |
| LinkedIn | 英文獨有 2 筆，兩筆職稱可辨識為 QA | 有限快照，不代表完整市場 |
| Yourator | 中英 union 25 筆，但 QA 相關命中很少 | 查詢語意／相關性未充分確認，不以原始數量算改善 |
| Web3.career | 舊查詢比較無效；分類修正後 15 筆、12 筆可辨識 QA | 分類仍含其他 assurance/testing 職務，需職務檢查 |
| DeJob | 英文回 13 筆，其中 12 筆可辨識 QA | 中文解析失敗，不能把英文 12 筆算成對中文的淨增量 |
| Cake／JobFrog／CryptoJobsList | 分別 HTTP 403／400／逾時 | 無法比較語言，不代表零職缺 |
| CryptocurrencyJobs／DeFi Jobs | 本次兩詞有限頁面均零命中 | 不代表整站沒有 QA 職缺 |

本次遠端欄位沿現有規則檢查；未知工作方式會保留，不等於已確認全遠端或可從台灣聘僱。

### 驗證、交付與操作

- 完整回歸：.venv/Scripts/python.exe -X utf8 -m pytest tests -q --ignore=tests/test_live_sources.py → 352 passed、2 deselected、1 既有 Starlette httpx warning，12.67s、exit 0。沒有增加依賴。直接對含方括號的 cwd 跑 pytest 曾被當 parametrization，未執行測試；改為明確 tests 路徑後通過。
- 前端 npm run lint 與 npm run build 均 exit 0；已重建 dist，1804 modules，Vite build 4.19s。
- [UI 檢查收據](2026-10-01-search-ui-check.json)：使用原 PDF、隔離無頭 Chromium、記憶體 DB 與受控 agent／來源回覆，8/8 通過：各站中英詞、DeFi 單次提示、來源失敗、零命中、正常零結果沒有範例，以及桌面與手機無橫向溢出。沒有真實 AI 呼叫，亦非使用者原生 Chrome／真人驗收。隔離服務已停止。
- git diff --check 通過。既有使用者修改保留，未 stage／commit／push／發布，未修改全域 Skill、Memory 或 AGENTS.md；方法落在本 repo 查詢規劃、adapter 註解、回歸與本節。

使用目前原始碼啟動器時，先停止舊搜尋並關閉舊服務，再重新跑 run.bat、重新上傳履歷。既有服務沒有自動 reload；獨立 exe 未重打包。本輪沒有自行中斷使用者服務或清除搜尋歷史。


## 16. Technical Support 履歷誤用後端搜尋詞修正（2026-10-01）

使用者提供 Technical Support Engineer (L3) 履歷，標題及 SUMMARY 明示 Seeking a fully remote Technical Support Engineer role；Python、API、SQL 為除錯、驗證與支援工具，並明示不是 product-development ownership。用原 PDF 執行修改前備援：preferred_roles 為後端工程師，queries 為後端工程師、Python 後端、Python，錯誤可重現。尚未取得使用者當次模型回覆／runtime，不判定當次一定觸發備援。

上一輪只加入 QA 保護，漏了 Technical Support。修改 [resume_eval.py](../../app/agents/resume_eval.py) 的主要職稱優先規則與模型 Profile 校正：Technical Support 標題優先；履歷明示 seeking Technical Support 時，修正模型自行推定的後端定位。修改 [job_search.py](../../app/agents/job_search.py)：純支援目標不由 Python 補成後端，模型搜尋詞限制在支援職務；直接 Profile 中明示的混合目標沿原行為。修改 [query_plan.py](../../app/sources/query_plan.py)：技術支援工程師有 Technical Support Engineer／Support Engineer 搜尋別名，並排除 Web3 QA 分類轉換，避免新別名被誤送 QA 分類。

共用方法：職務保護需涵蓋主職稱與明示目標，不能只為 QA 加特例；先修 Profile，再限制衍生搜尋詞，最後才做來源語言別名。技術支援的 troubleshooting／validation 工具不當作開發求職意願。未知職務仍未具完整通用分類，不宣稱所有職務都已校正；海外來源對技術支援詞的實際召回與 Web3 非 QA 搜尋路由語意本輪未驗。

新增六項回歸：主要 Support 職稱優先於舊 QA／Firmware、明示 Support 修正模型後端角色、純 Support 工具不生後端詞、錯誤模型查詢詞被擋、相關詞與明示混合目標保留、中英別名不轉成 Web3 QA 分類。完整 pytest tests -q --ignore=tests/test_live_sources.py：358 passed、2 deselected、1 既有 Starlette httpx warning，5.01s，exit 0；git diff --check 通過。

原 PDF 上傳至隔離 TestClient（記憶體 DB、受控模型及空搜尋結果），分別模擬 parser failure 與模型 Profile／queries 同時回後端。兩次 HTTP 200；preferred_roles 與 queries 都為技術支援工程師，104 實際詞為技術支援工程師、Technical Support Engineer、Support Engineer；LinkedIn 實際詞為 Technical Support Engineer、Support Engineer。未保存履歷全文或個資至 repo、未呼叫真實 AI／網站、未寫正式 DB。

本批只改後端／測試／交付文件，前端未變，不重建。沒有中斷使用者舊服務，使用 run.bat 者須關閉舊服務後重啟並重新上傳；已儲存的舊 Profile 不會自動回寫。獨立 exe 未重打包，無提交／推送／發布。


## 17. QA Manager 目標被降成工程師搜尋詞修正（2026-10-01）

使用者提供 William-Lu-QA-Manager-Resume.pdf。實際文字明示 Target Role: QA Manager，以及 Seeking a QA Manager role；內容包括六人團隊領導、績效考核、coaching、測試規劃及交付管理。原備援將所有 QA 視為工程師，得到 QA 工程師、測試工程師、自動化測試工程師。

修正 [resume_eval.py](../../app/agents/resume_eval.py)：管理目標先於一般 QA 規則；明示 Target Role／Seeking 目標獨立於版面位置判讀。原 PDF 的頁碼與重複姓名使 Target Role 落在第 5 行，第一次原附件 API 檢查因此失敗；已補回歸並修正，不能只用簡短文字 fixture 代替原附件。明示管理目標會校正模型誤回的工程師定位。

修正 [job_search.py](../../app/agents/job_search.py)：純 QA Manager 目標的備援與模型搜尋詞都保留管理層級，自動化工具不降成工程師；直接 Profile 中明示 Manager 與 Engineer 混合目標仍保留。修正 [query_plan.py](../../app/sources/query_plan.py)：104／Yourator／Cake 使用 QA 經理及 QA Manager、Test Manager、Quality Assurance Manager；海外來源用上述英文詞。管理別名不折疊為一般 QA 查詢。

[source_web3career.py](../../app/sources/source_web3career.py) 的管理詞沿已驗證 QA 分類入口抓取後，額外按職稱 manager／經理／主管篩選，避免回到語意未驗證的舊搜尋 URL；分類有職缺但沒有管理職時回正常零結果。這是職稱層級檢查，並非管理職責、軟體領域或台灣遠端資格的人工作業查證；本輪沒有即時外站補驗。

共用方法：職務家族、目標層級及技能分開判讀；明示目標優先於舊工作與工具，明示目標不限制在 PDF 前幾行；每次使用提供的原附件驗證上傳流程，另以去個資 fixture 留回歸。方法已落程式／提示詞及本節，沒有修改全域 Skill、Memory 或 AGENTS.md。

新增七項回歸涵蓋頁碼推移後的管理目標、錯誤模型 Profile／搜尋詞、純管理與混合目標、中英層級別名、Web3 分類管理職篩選及零結果判讀。完整測試 .venv/Scripts/python.exe -X utf8 -m pytest tests -q --ignore=tests/test_live_sources.py：365 passed、2 deselected、1 既有 warning，5.05s，exit 0。第一輪 364 passed／1 failed 是混合目標測試預期誤含既有規則不接受的 Test Manager；修正預期後通過，再補原 PDF 版面漏判後完整重跑。

原 PDF 透過隔離 TestClient（記憶體 DB／假搜尋）上傳，parser failure 與模型回錯 QA 工程師等三詞兩種情境皆 HTTP 200：roles／queries 為 QA 經理；104 為 QA 經理、QA Manager、Test Manager、Quality Assurance Manager；LinkedIn／Web3 為 QA Manager、Test Manager、Quality Assurance Manager。未送真實 AI／網站、未寫正式紀錄、未存履歷全文。

只改後端、測試、交付文件，前端未變；未重打包 exe、未提交推送發布。舊服務需關閉重啟 run.bat，再重新上傳 PDF；舊 Profile 沒有自動更新。本輪只驗管理搜尋層級，不宣稱所有職務或實際搜尋召回已完整驗收。


## 18. 自動初查全遠端與台灣工作地區（2026-10-01）

已完成本次授權範圍。使用原始碼版者須關閉舊服務、重新啟動 run.bat，再上傳履歷並重新搜尋；舊搜尋紀錄保留當時快照，不會自動重新查證。獨立 exe 未重打包。

### 畫面與實際案例

搜尋預設開啟「優先找全遠端、可從台灣工作的職缺」。系統在適配度評分前讀取職缺連結，分別判斷全遠端與台灣工作地區：兩項通過放入推薦；資訊不足、互相矛盾或讀取失敗放入待確認；任一項明確不符合放入可展開的排除清單。卡片保留原文／欄位依據、來源網址與查詢時間。其他條件的手動紀錄收在選填區，不覆蓋自動結果。

本次實際讀取 Sardine 官方 Customer Support Engineer 頁面：Location Type: Remote，但 Location: Remote - Brazil，且申請地區限制 Brazil。結果為全遠端通過、台灣工作地區不通過；API 不送它進入適配度排序，沒有載入範例補成推薦。原本需要本人點入發現巴西限制，現在系統自動排除並留依據。實測完整收據：[Sardine 官方頁面檢查](2026-10-01-sardine-remote-check.json)。

### 判讀方法與界線

- 先判讀職缺本身的地點與居住限制，再看公司文化描述；remote-first、產品支援 remote troubleshooting、公司有全球辦公室，均不能單獨確認這個職缺全遠端。Remote 與 APAC 單獨出現，也不能確認接受台灣。
- 明確其他國家限制優先於一般 worldwide 宣傳；限制條款只取工作／居住地區，服務台灣客戶不能當作接受台灣居住。互相矛盾的條件保留待確認。
- JSON-LD 只採用 JobPosting 的工作地點與 applicantLocationRequirements，不把 Organization 的總部當職缺限制；欄位值轉為可讀依據。一般 HTML 沿既有文字擷取。
- 每次搜尋最多讀 40 個不同 URL、同批 4 個；45 秒後停止啟動新批次，已開始的請求仍會結束。8 秒為單次連線／讀取 timeout，並非整場搜尋的硬期限。重複 URL 共用本次搜尋快取。
- 讀取失敗、需要登入／JavaScript、國家或措辭未涵蓋、頁面文字超過 8,000 字而截斷、時間／數量不足，都保留待確認，不能補成通過。使用者只需對感興趣的待確認職缺進一步詢問。
- 通過只代表已讀頁面接受台灣工作地區且寫明遠端；不保證台灣聘僱、EOR、合約、輪班或待遇。搜尋紀錄是查詢時間的快照，重新搜尋才取得新結果。
- Ashby 官方頁面原 httpx 讀取逾時，本次改用 repo 既有 requests 依賴處理該公開主機，逐次 redirect 仍檢查主機／IP，保留 5 MB 上限，沒有關閉 TLS 或加入代理／新依賴。

### 接線與驗證

[remote_eligibility.py](../../app/intake/remote_eligibility.py) 為判讀與有限批次讀取；[jd_fetch.py](../../app/intake/jd_fetch.py) 擷取公開頁面；[server.py](../../app/server.py) 在一般與公司池排序前檢查。新前端預設送 taiwan_remote=true，舊 API 呼叫未提供時維持 false。結果存入搜尋 payload，不新增 SQL schema，也不寫手動查證表。

- 完整回歸：.venv/Scripts/python.exe -X utf8 -m pytest tests -q --ignore=tests/test_live_sources.py → 397 passed、2 deselected、1 既有 Starlette httpx warning，7.95s，exit 0。
- 前端 npm run lint 與 npm run build 均 exit 0；dist 已重建，1804 modules，8.64s。
- [畫面檢查收據](2026-10-01-remote-check-ui.json)：隔離無頭 Chromium、記憶體 DB、受控來源／頁面／agent，12/12 通過，包含預設啟用、三組結果、排除原因與依據、桌面／手機無橫向溢出、搜尋紀錄及重新整理保留結果。不是使用者原生 Chrome 或真人驗收。
- 官方 Sardine 實測使用真實公開頁面與真正判讀程式；來源清單、Profile 與 AI 為受控資料，記憶體 DB，HTTP 200，rank_total=0、demo_loaded=false。未宣稱全部來源或真實 AI 全流程均通過。
- 隔離服務已停止。本次未寫正式 DB、未中斷使用者服務、未提交／推送／發布、未修改全域 Skill、Memory 或 AGENTS.md；既有修改保留。方法修正落在本 repo 判讀程式、回歸測試及本節。
