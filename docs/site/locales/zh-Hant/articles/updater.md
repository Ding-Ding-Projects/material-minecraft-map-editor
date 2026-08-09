# 未簽署 Squirrel 更新

Windows 應用程式會喺啟動後檢查列入允許清單嘅 HTTPS Squirrel feed，
之後每六小時再檢查一次。非阻塞橫幅會報告有更新、已準備、失敗同目前版本
狀態。暫存前會驗證 feed 中繼資料同套件雜湊；只會喺使用者揀咗
**重新啟動並安裝更新**之後先安裝。**稍後**會收起橫幅，但唔會丟棄已暫存狀態。

## 設定同失敗情況

feed 預設使用專案嘅不可變發行下載路徑。無效網址、離線回應、格式錯誤嘅
中繼資料、雜湊唔一致、取消，或者未儲存工作，都只會產生可復原嘅失敗狀態，
絕對唔會打斷進行中嘅編輯。應用程式永遠唔會呼叫簽署工具，而每件已發佈嘅
Windows 成品都會清楚標明未經簽署。

## 保安同無障礙

主機必須喺允許清單內；重新導向同內嵌憑證會被拒絕；暫存前亦會檢查套件
雜湊。重新啟動會保留未儲存工作保護同焦點。橫幅可以用鍵盤到達，已本地化，
而且會保留到使用者關閉，並寫入去重複嘅歷史記錄。

## 驗證

執行 `python -m pytest -q tests/test_updater_banner_contract.py tests/api/framework/test_squirrel_update.py tests/api/framework/test_update_copy.py`。
託管證明係 Windows 工作流程嘅 Squirrel 成品同未簽署合約，唔係一個靜態原始碼檢查。

建議文章：[本機歷史](../local-history/README.md)、
[通知中心](../notification-centre/README.md)，以及
[離線說明文件](../offline-documentation/README.md)。
