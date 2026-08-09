# 發行版本點心代號

## 行為

Windows 發行工作流程會由公開 `Ding-Ding-Projects/dim-sum-photos` 圖錄揀一個未用過嘅雙語點心名稱。只有圖片檔名已經出現喺已發佈 `catalog-v1*` 發行資產入面嘅點心先會入選；之後，工作流程會喺發行說明記錄準確英文名、繁體中文名，同埋不可變公開資產網址。

## 設定同失敗情況

解析器會喺發佈期間使用網絡，亦接受可選嘅 `GH_TOKEN`，增加 GitHub API 速率限制餘額。如果圖錄、發行清單、雙語名稱或者公開圖片資產有任何一項驗證唔到，佢就會安全失敗，避免估出嚟嘅代號混入發行版本。公開圖錄恢復可用之後，可以重新嘗試發行。

## 保安

圖錄數值只會解析成固定工作流程輸出鍵，永遠唔會交畀 shell 求值。發行說明會連結公開資產，唔會將相片複製入呢個儲存庫，亦唔會附加重複嘅消費者資產。

## 驗證

執行 `py -3 -m pytest -q tests/test_dim_sum_release_code.py`，驗證決定性選擇同安全失敗測試。執行 `python scripts/resolve_dim_sum_code_name.py`，就可以喺本機測試實時公開圖錄界線。

## 建議文章

- [點心驚喜](../dim-sum-surprise/README.md)
- [Squirrel 封裝](../../../installer/PACKAGING.md)
- [離線說明文件瀏覽器](../offline-documentation/README.md)
