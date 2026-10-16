# 變更紀錄

每個版本都會註明它跟隨的 Chromium 版本。跟隨較新 Chromium 版本的發布，即使 API 沒變，凡是 Chromium 改了規則的地方，回傳的檔名也可能不同。

## 0.1.0

- 首次發布，跟隨 Chromium `dfd5cca812cefda32e909ae39965ed22041d5e65`（main，2026-10-16）及其 ICU 78。
- `suggested_filename()` 回傳 Chromium 替一次下載建議的檔名，`parse_content_disposition()` 照 Chromium 的方式讀取 Content-Disposition 標頭。兩者都接受位元組或字串形式的標頭。
- 純 Python、沒有相依套件，支援 CPython 3.11 以上和 PyPy。
