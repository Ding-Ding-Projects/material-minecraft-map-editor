# Windows 發行交付合約

## 行為

每次成功推送或者手動分派，都會建置 Windows 應用程式、執行發行閘門測試、
封裝未簽署 Squirrel.Windows 發行版本，再發佈一個唯一、非草稿版本。必要資產係
`Setup.exe`、`RELEASES` 同完整 `.nupkg`；如果產生咗 delta 套件，
亦會一齊交付。

推送同發行建置會喺已發佈發行清單搜尋較舊完整套件。只有檔案、NuGet 套件身分、
檔名／中繼資料版本一致，而且版本嚴格較舊都驗證通過，候選先會成為 delta 基礎。
如果冇安全候選，Squirrel 仍然會產生必要完整發行版本，但唔會有 delta。

自動發佈先建立帶遞迴標記嘅草稿，之後只發佈一次。工作流程會讀取結果嘅
`publishedAt` 時間戳，再由第一個部署工作開始計算經過時間。最終說明包括呢段
已驗證時距，同埋已提交行數表。

## 設定

工作流程位於 `.github/workflows/build-windows.yml`。發行 API 呼叫依次使用
`RELEASE_TOKEN`、`ORG_TOKEN`，最後先用工作流程權杖。封裝只限 Windows，
程式碼簽署保持停用。`scripts/count_lines.py` 會計已追蹤嘅逐行文字，報告手寫
專案列、已產生同排除列、專案同儲存庫總計，以及仍然存在嘅代理／人員／未歸屬
`git blame` 行。

## 失敗情況

- 測試或者套件建置失敗會阻止發佈。
- 較舊套件遺失或者唔安全，只會跳過 delta 產生；必要完整資產仍然必須存在。
- 第一個工作或者發佈時間戳遺失時，發行說明會失敗，唔會作一個時間出嚟。
- 已存在嘅不可變資產名稱永遠唔會被覆寫。
- 歸屬或者總數算術唔一致，已提交計數器就會失敗。

## 保安

發行權杖只留喺工作流程憑證環境，永遠唔會列印。事件標籤資料正規化之後先交畀
CLI。較舊套件必須係有效 NuGet ZIP 檔案，屬於 `Amulet` 套件，而且嚴格早過
候選版本。執行檔同 DLL 必須報告 `NotSigned`；工作流程永遠唔會要求或者呼叫簽署。

## 驗證

執行：

```powershell
py -3 -m unittest -v tests.test_windows_workflow_contract tests.test_release_timing tests.test_squirrel_delta_base tests.test_count_lines
actionlint -shellcheck= .github/workflows/build-windows.yml
py -3 scripts/count_lines.py
```

上面 `actionlint` 指令係 Windows 主機結構檢查。託管 Linux 工作流程仍然負責
檢查 shell 本文。

## 建議文章

- [發行代號](../release-code-name/README.md)
- [更新程式](../updater/README.md)
- [建置指令碼](../build-scripts/README.md)
- [Squirrel 封裝](../../../installer/PACKAGING.md)
