# 外部編輯器整合

Amulet 可以用本機已安裝、兼容 Visual Studio Code 嘅編輯器開啟已匯出檔案
或者資料夾。整合刻意喺 `amulet_map_editor.api.external_editor` 保持同 wx
無關，所以桌面介面、無介面測試或者未來說明文件介面嘅匯出流程，都可以共用
同一套驗證同結果合約。

## 行為

- 偵測會檢查 `code` 同 `code-insiders`（喺 `PATH` 上）、一般 Windows
  每使用者／全系統安裝、Scoop 安裝，同埋一個有界限嘅
  `VSCODE_PORTABLE` 位置。現存檔案會以決定性次序去重複。
- 偏好設定只會儲存已揀執行檔路徑。路徑上限係 4096 個字元，而且每次使用
  都會重新驗證，所以移除或者搬走 Code 只會產生可復原嘅不可用狀態，唔會崩潰。
- 原生**偏好設定 → 外觀**分頁提供路徑欄、原生瀏覽按鈕，同埋非阻塞
  **檢查編輯器**動作。欄位會暫存到按**確定**儲存偏好設定為止。
- 開啟檔案會用該檔案路徑呼叫所揀編輯器。開啟資料夾會加上
  `--folder-uri`，令資料夾成為工作區根目錄。所有啟動都會包括
  `--reuse-window`，並傳回結構化結果。
- 通知歷史、外觀預設、變更記錄，同埋本機歷史匯出，寫好檔案之後都提供
  同一個**喺 VS Code 開啟匯出項目**動作。共用
  `api.export_actions.open_exported_path` 轉接器令動作保持非阻塞：未設定、
  過期或者啟動失敗嘅編輯器會傳回可見嘅 `unavailable`、
  `invalid_target` 或者 `launch_failed` 結果，而匯出檔案仍然留喺磁碟。

## 失敗情況同保安

橋接器永遠唔會經指令直譯器呼叫 shell，亦唔會將路徑插入指令字串。
遺失、唔係檔案、過長或者過期嘅路徑會傳回 `not_configured`、
`invalid_target` 或者 `unavailable` 結果。啟動失敗會傳回
`launch_failed`，並將原本 `OSError` 訊息交畀原生通知介面。橋接器除咗
檢查要求嘅路徑之外，唔會讀取編輯器設定、憑證、工作區內容或者使用者檔案。

## 驗證

```text
python -m unittest tests.test_external_editor tests.test_external_editor_ui_contract
```

測試包括決定性 PATH／位置探索、去重複、選擇持久化、資料夾工作區根目錄參數，
以及唔啟動真正編輯器程序嘅安全不可用結果。`tests.test_export_actions`、
`tests.test_export_ui_contract` 同本機歷史匯出測試，會覆蓋共用匯出動作、
原生接線，同埋安全嘅編輯器不可用路徑。
