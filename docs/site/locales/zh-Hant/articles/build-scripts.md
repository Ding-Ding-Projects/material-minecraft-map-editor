# 一鍵式 Windows 建置指令碼

## 行為

`build.bat` 會偵測 Python 3.11；有需要時，透過 `winget` 或者官方
python.org 安裝程式為目前使用者安裝；再重新整理目前程序嘅路徑、安裝已宣告嘅
建置／執行階段相依項，最後以可編輯模式安裝套件。`/s`、`--silent` 或者
`SILENT=1` 都會抑制提示。

`build-installer.bat` 會呼叫靜默原始碼啟動程序、安裝 PyInstaller、
建置 `installer/Amulet.spec`，再走同 CI 一樣嘅鎖定版 Squirrel.Windows
路徑。佢會先驗證 `Setup.exe`、`RELEASES` 同完整套件，先至列出 SHA-256
摘要。兩個指令碼都唔會簽署、發佈、加標籤或者建立發行版本。

## 失敗同保安界線

啟動程序只影響目前使用者；如果安裝之後仍然啟動唔到 Python 3.11，
就會安全失敗。程式碼簽署同憑證資料刻意完全唔存在。產生嘅 Squirrel
成品未經簽署，Windows 可能會顯示未知發行者或者 SmartScreen 警告。

## 驗證

喺 2026-08-09，呢個檢出版本通過 `cmd /c build.bat /s` 同
`cmd /c build-installer.bat /s`；後者喺本機產生齊三個必要、未簽署嘅
Squirrel 成品。CI 仍然係發行版本嘅權威證據。
