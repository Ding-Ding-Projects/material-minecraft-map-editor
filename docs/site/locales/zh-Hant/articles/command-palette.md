# 指令面板

喺 Windows 按 `Ctrl+Shift+F` 就可以開啟原生指令面板。結果包括指令、
功能目的地、設定、外觀控制項，同埋說明文章。揀選結果之後，程式會開啟所屬
介面、揀啱分頁或者群組、顯示目標、將焦點放過去，同時保留使用者其餘狀態。

## 搜尋同失敗情況

預設係純文字。附帶嘅正則表達式建立器支援有界限嘅 Python `re` 模式、
旗標、範例、驗證同擷取回饋。無效或者過大嘅模式會喺本機失敗，並顯示可以
採取行動嘅訊息，唔會凍結介面。冇結果時會清楚講明，唔會留低一塊空白面板。

## 無障礙同保安

指令面板可以用鍵盤同移動式選取操作，有清晰焦點，亦有螢幕閱讀器 listbox
角色。搜尋值只留喺目前程序，唔會傳送或者持久化做遙測。School mode
會由結果清單移除唔適用嘅目的地。

## 驗證

執行 `python -m pytest -q tests/test_preferences.py tests/test_docs_browser_ui_contract.py`。
因為本機主機未必安裝咗 wx，執行階段快捷鍵證明需要隱藏桌面 Windows 路徑。

建議文章：[離線說明文件](../offline-documentation/README.md)、
[分頁群組](../tab-groups/README.md)，以及
[外觀編輯器](../appearance/README.md)。
