# Rich Menu 自訂圖

## 兩種覆寫方式

### 覆寫單格 icon（推薦）

丟 PNG 進這個資料夾，檔名照下表，**建議 400×400 px、透明背景**：

| 角色 | 按鈕順序 | 檔名 |
|---|---|---|
| 老師 | 1 派新作業 | `teacher_1.png` |
| 老師 | 2 今日作業 | `teacher_2.png` |
| 老師 | 3 歷史紀錄 | `teacher_3.png` |
| 老師 | 4 未完成 | `teacher_4.png` |
| 老師 | 5 完成統計 | `teacher_5.png` |
| 老師 | 6 說明 | `teacher_6.png` |
| 學生 | 1 今日作業 | `student_1.png` |
| 學生 | 2 我完成了 | `student_2.png` |
| 學生 | 3 傳照片 | `student_3.png` |

沒放的格子會自動用預設漸層+emoji。

### 覆寫整張圖（進階）

如果你想用 Figma / Photoshop 整張排版好，存成 PNG 直接丟：

- 老師：`teacher_full.png` 尺寸 **2500×1686**
- 學生：`student_full.png` 尺寸 **2500×843**

整張模式會忽略所有單格設定，但按下去的熱區（每格 width/3）不會變，畫面上的按鈕位置要對齊。

## 改完之後

重跑一次 setup：
```powershell
curl.exe -X POST -H "X-Cron-Token: <你的 CRON_SECRET>" http://localhost:8000/cron/admin/setup-rich-menu
```

## 推薦的免費圖庫

- https://www.flaticon.com/ — 種類最多，免費用要標註作者
- https://icons8.com/ — 風格統一
- https://fonts.google.com/icons — Material 風格
- https://openmoji.org/ — 開源 emoji
