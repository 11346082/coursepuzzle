# 課拼 CoursePuzzle

把課，一片片拼對。選課、校園公告、活動報名、日曆與待辦，放在同一個 Django 系統裡。

## 啟動

```bash
python -m venv .venv
source .venv/bin/activate          # Windows：.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations courses
python manage.py migrate
python manage.py seed_demo         # 建立示範資料與測試帳號
python manage.py runserver
```

開啟 http://127.0.0.1:8000/

> 如果之前跑過舊版：請刪除 `db.sqlite3` 與 `courses/migrations/` 裡以 `0` 開頭的檔案，再重新執行上面的指令。

## 測試帳號

| 身分 | 帳號 | 密碼 |
| --- | --- | --- |
| 學生 | s1001 ~ s1006 | demo1234 |
| 老師 | t_lin、t_chang、t_wu、t_huang、t_cheng、t_liu ... | demo1234 |
| 教職員 | admin（後台 /admin/） | admin1234 |

## 功能

**選課**
- 課程查詢：關鍵字、開課單位、課別、學分、整天不想上課、不要早八、中午留空、只看有名額
- 課程詳情：簡介、學習目標、評量方式、教材、每週進度、老師公告、修課心得、「同學也選了」
- 加退選與四種狀態（可加選、已加選、額滿、衝堂），失敗會說明原因，例如「與『資料庫管理』週二第 4、5 節衝堂」
- 額滿候補：有人退選時依登記順序自動遞補並發通知；老師調高名額時也會自動遞補
- 智慧排課：輸入目標學分與空堂需求，產生最多三套不衝堂方案，一鍵套用
- 收藏清單一鍵加選
- 我的課表：週課表、加選前預覽、學分進度與課別統計、每週到校天數，可匯出 .ics 到 Google 日曆或 Apple 行事曆

**校園**
- 校園公告：教務、學務、活動、獎助、系統分類，置頂
- 校園活動：講座、社團、徵才、服務學習，線上報名與取消，名額控管
- 校園日曆：整月檢視，顯示活動、學期與選課日期、自己的待辦期限

**個人**
- 待辦事項（逾期標示）、通知中心（含未讀數量）、個人資料

**老師**：編輯大綱與公告、調整名額、查看候補與修課名單、匯出 CSV

**教職員**：用 Django 後台維護課程、開課、時段、學期與選課時間、公告、活動、使用者與身分

## 雲端登入（Google、Microsoft）

登入頁提供 Google 與 Microsoft 按鈕，也保留帳號密碼登入。沒有設定金鑰的按鈕會顯示「尚未設定」，不影響其他功能。

1. 複製 `.env.example` 成 `.env`，填入金鑰（`.env` 已列在 `.gitignore`，不要上傳）。
2. **Google**：Google Cloud Console，建立專案，設定「OAuth 同意畫面」，再到「憑證」建立「OAuth 用戶端 ID」，類型選「網頁應用程式」。
   「已授權的重新導向 URI」填入：`http://127.0.0.1:8000/auth/google/callback/`（若你用 localhost 開網站，也要另外加 `http://localhost:8000/auth/google/callback/`）。
   把用戶端 ID 與密鑰填到 `GOOGLE_CLIENT_ID`、`GOOGLE_CLIENT_SECRET`。
3. **Microsoft**：Azure 入口網站，Microsoft Entra ID，「應用程式註冊」，新增註冊，重新導向 URI 類型選 Web，填入 `http://127.0.0.1:8000/auth/microsoft/callback/`。
   在「憑證和密碼」建立用戶端密碼，填到 `MICROSOFT_CLIENT_ID`、`MICROSOFT_CLIENT_SECRET`。只允許學校帳號時，把 `MICROSOFT_TENANT` 改成學校的租用戶 ID。
4. 想只開放學校信箱：設定 `SOCIAL_ALLOWED_DOMAINS`（例如 `ntub.edu.tw`，多個網域用逗號分隔）。測試時留空。
5. 重新啟動 `runserver`。網址必須和你在服務商登記的完全一致（127.0.0.1 與 localhost 視為不同）。

行為說明：
- 第一次用雲端帳號登入會自動建立「學生」帳號，信箱若是純數字開頭會當成學號。
- 老師與教職員身分由教務處在後台指派：在後台建立使用者、填入同一個信箱，並在「身分資料」選擇老師或教職員，之後用雲端帳號登入就會對應到這個帳號。
- 只有信箱經過服務商驗證（Google）或已限制學校網域（Microsoft）時，才會對應到既有帳號。

## 匯入真實課程資料

示範資料的系所架構參考臺北商業大學公開資訊，但課程內容、時段、教室、老師與學生都是虛構的。要換成真實資料：

```bash
python manage.py import_courses data/courses_sample.csv --semester 115-1
```

CSV 欄位與時段格式請看 `courses/management/commands/import_courses.py` 開頭的說明與 `data/courses_sample.csv`。老師帳號需要先在後台建立（欄位 `teacher_username` 對應帳號）。

## 專案結構

- `courses/models.py`：資料模型（課程、開課、時段、選課、候補、心得、公告、活動、待辦、通知、雲端登入綁定）
- `courses/services.py`：衝堂檢查、加退選、候補遞補、智慧排課、.ics 匯出
- `courses/social.py`：Google、Microsoft 雲端登入（OAuth 2.0，標準函式庫實作）
- `courses/views.py`、`courses/urls.py`：頁面
- `courses/demo_data.py`、`seed_demo.py`：示範資料
- `templates/`、`static/css/style.css`：版面與樣式（暖色系、拼圖主題）

## Demo 流程（約 10 到 12 分鐘）

1. 首頁：介紹拼圖主視覺、功能入口與最新公告
2. 用 s1001 登入：首頁出現今天的課、待辦與學分進度
3. 課程查詢，勾選「不要早八」「只看還有名額」，點進「資料庫管理」看簡介、目標與每週進度
4. 資料庫管理額滿：按「加入候補」，到通知中心看到候補順位
5. 按某門衝堂課的「預覽」，課表格子變紅並說明衝堂原因
6. 智慧排課：選 15 學分，比較三套方案，按「一鍵套用」
7. 我的課表：看學分與到校天數，匯出 .ics
8. 登出，用 s1002 登入並退選資料庫管理，再回 s1001 的通知中心：候補已自動遞補
9. 校園活動報名、校園日曆看到報名的活動與待辦期限
10. 用 admin 在後台發布公告、新增課程，回學生端立刻看到
11. 用 t_chang 登入，調高資料庫管理名額，看到老師端的候補與名單
