# 本機歷史

Amulet 本機歷史係一條只可附加、以 Git 支援嘅稽核記錄，用嚟保存應用程式擁有嘅
記錄，例如設定、通知，同未來文件中繼資料。佢刻意同使用者已開啟專案分開：
預設儲存庫位於作業系統應用程式資料目錄（Windows 係
`%APPDATA%/AmuletMapEditor/history`、Linux 係
`$XDG_DATA_HOME/AmuletMapEditor/history`，macOS 就用對應 Application Support
目錄）。呼叫者可以提供測試或者資料檔路徑，但歷史 API 永遠唔會由專案資料夾
推導路徑。

## 行為

`LocalHistory.record()` 會儲存有界限 JSON 快照，再提交成一個新本機 Git
提交。第一個快照係 `created`，之後嘅改動係 `updated`。`delete()` 會記錄
`deleted`，並喺不可變事件保留舊值，所以 `restore(event_id)` 可以建立新
`restored` 事件，唔使改寫較早歷史。冇變更嘅快照唔會產生事件。事件檔案有
唯一 ID，之後寫入永遠唔會取代佢哋。

儲存亦提供純文字優先搜尋、明確選用嘅正則表達式、動作／類型／日期篩選、
JSON 同 Markdown 匯出，以及檔案匯出。查詢同負載都有大小限制。正則表達式
要自願啟用，所以設定名稱例如 `[` 仍然係普通文字，唔會意外變成無效模式。

原生**檢視 → 本機歷史…**對話框提供有界限搜尋、明確正則表達式模式、動作篩選、
日期選擇器、多選、**全部揀選**、**反轉選擇**、批次還原成新事件、JSON 匯出，
同埋**喺 VS Code 開啟匯出項目**動作。`Ctrl+A` 會揀可見事件，`Ctrl+I`
反轉選擇，而 `Enter` 會還原已揀事件。部分還原會報告完成數目同準確失敗，
唔會扮成整批成功。歷史介面保持非阻塞，並經一般對話框關閉路徑交還焦點。

`LocalHistory.export_and_open()` 會先寫好所揀 JSON 或者 Markdown 匯出，
再用共用外部編輯器動作交畀 VS Code。編輯器不可用時，結構化結果會報告安全
失敗，而匯出檔案仍然完整留喺磁碟。

## 失敗同保安界線

歷史係稽核輔助，唔係操作嘅權威來源。主要操作周邊應該使用
`safe_record`、`safe_delete`、`safe_restore`，或者一次性
`safe_record` 輔助函式：冇 Git、資料檔不可寫、歷史損壞，同驗證失敗都會
傳回 `None`，唔會阻塞設定／文件改動。負載係有限 UTF-8 JSON，上限 1 MiB。
記錄 ID 會雜湊成檔名，所以使用者文字唔可以穿越歷史目錄。憑證同專案檔案
唔會由歷史模組複製入呢個儲存庫。

本機儲存庫使用固定本機作者身分，冇設定上游。除非未來使用者介面匯出流程
明確提供選擇，否則永遠唔會同步或者推送。還原本身亦係新提交，令復原操作
仍然可以再復原。

## 驗證

`tests/test_local_history.py` 會測試預設應用程式資料位置、
created／updated／deleted／restored 提交、冇變更抑制、純文字同正則搜尋、
日期篩選、匯出、有界限負載，同非阻塞安全包裝器。模組冇 wx 相依，
可以喺無介面執行器測試。

## 建議文章

- [排程設定](../scheduled-settings/README.md) — 喺同一本機歷史記錄臨時覆寫同復原。
- [通知中心](../notification-centre/README.md) — 翻查同匯出已關閉通知。
- [外觀預設](../appearance-presets/README.md) — 將命名外觀改動保留成使用者擁有記錄。
