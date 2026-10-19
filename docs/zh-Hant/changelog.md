# 變更紀錄

每個版本都會註明它跟隨的 Chromium 版本。跟隨較新 Chromium 版本的發布，即使 API 沒變，凡是 Chromium 改了規則的地方，回傳的檔名也可能不同。

## 0.2.1

- 跟 0.2.0 一樣，跟隨 Chromium `dfd5cca812cefda32e909ae39965ed22041d5e65`（main，2026-10-16）及其 ICU 78。
- import 本套件時不再載入 `importlib.metadata`，它原本佔了 import 時間的一半以上；`__version__` 改在第一次用到時才讀取已安裝的版本。
- 使用方式說明了如何命名而不加上 Content-Type 的副檔名：見[不理會 Content-Type](usage.md#ignore-the-content-type)。

## 0.2.0

- 跟 0.1.0 一樣，跟隨 Chromium `dfd5cca812cefda32e909ae39965ed22041d5e65`（main，2026-10-16）及其 ICU 78。
- `suggested_filename()` 改為接受回應的整組標頭，並照 Chrome 的方式從中推導 MIME 類型（但不檢查內容）；新增的 `sanitize_filename()` 可以清洗任何來源的名稱。為 0.1.0 寫的呼叫可能需要下列修改。

### 不相容的改動 {#incompatible-changes}

| 0.1.0 | 0.2.0 |
| --- | --- |
| `suggested_filename(url)` | `suggested_filename(url=url)` |
| `suggested_filename(url, header)` | `suggested_filename(url=url, content_disposition=header)` |
| `suggested_filename(None, header)` | `suggested_filename(content_disposition=header)` |
| `suggested_filename(url, suggested_name=name)` | `suggested_filename(url=url, download_attribute=name)` |
| `suggested_filename(url, mime_type=content_type)` | `suggested_filename(url=url, content_type=content_type)` |
| `suggested_filename(url, default_name="")` | `suggested_filename(url=url, default_name=None)` |
| 在 Windows 上執行的 `suggested_filename(url=url, content_disposition=header)` | `suggested_filename(url=url, content_disposition=header, platform="posix")` |
| `parse_content_disposition(value=header)` | `parse_content_disposition(header)` |

- `suggested_filename()` 只有一個引數能以位置傳入，就是新的 `headers`，而它不能是字串或位元組：以位置傳入網址或標頭會丟出 `TypeError`。
- `suggested_name` 改名為 `download_attribute`；`mime_type` 改名為 `content_type`，它是伺服器送出的原樣 Content-Type 標頭（見〈行為改動〉）。
- `default_name=None` 表示改用網址的主機名稱。0.1.0 用空字串的 `default_name` 表示這件事，0.2.0 則會丟出 `ValueError`。
- `platform` 的預設值改為 `None`：在 Windows 上執行時採用 Windows 的規則，在其他系統上採用 POSIX 的規則。0.1.0 在任何系統上都採用 POSIX 的規則；在 Windows 上要得到跟它相同的檔名，就傳入 `platform="posix"`。
- `parse_content_disposition()` 的 `value` 只能以位置傳入。

要改傳回應的整組標頭、而不是單一個標頭，見[使用方式](usage.md#pass-the-headers-from-your-http-library)。

### 新功能 {#new-features}

- `suggested_filename(headers, url=...)` 接受回應的標頭：mapping，或由 `(名稱, 值)` 配對組成的 iterable，值是字串或位元組（型別是 `HeadersLike`，可以匯入來標註型別）。第一行 Content-Disposition 的第一個值決定檔名，各行 Content-Type 與 X-Content-Type-Options 決定 MIME 類型。`content_disposition` 和 `content_type` 不是 `None` 時，會取代這些行。
- `parse_content_disposition()` 也接受回應的整組標頭，結果多了一個欄位 `blocks_download`：Chrome 是否因為 Content-Disposition 的值（在引號外的逗號處切開）不全相同，或標頭裡有 NUL，而拒絕這個回應。`suggested_filename()` 照樣用第一個值決定檔名。這個欄位參與相等比較，也出現在 repr 裡：`attachment; filename=a,b.txt` 的結果不再等於 `ContentDisposition("attachment", "a")`。
- `headers_encoding` 指定你的 HTTP 函式庫解碼標頭時用的 codec，例如 requests 和 `urllib.request` 是 `"latin-1"`，用來把每一個字串形式的標頭值精確還原成解碼前的位元組。
- `content_type` 也接受位元組。
- `sanitize_filename()` 清洗任何來源的名稱，例如網頁標題，清洗方式跟 Chrome 清洗 `<a download>` 的值相同。
- [使用方式](usage.md#pass-the-headers-from-your-http-library)示範了怎麼從 httpx2、httpx、requests、aiohttp 和 `urllib.request` 傳入標頭，測試也會用這些函式庫實際取回回應來檢查。

### 行為改動 {#changed-behavior}

有些呼叫在 0.2.0 會得到不同的結果，分成三類。

**更接近 Chromium。**

- 每一個標頭值，包括 `content_disposition`、`content_type` 和 `parse_content_disposition()` 的 `value`，都當成該行標頭照送出時原樣的其餘部分來讀（見[讀取標頭行](behavior.md#reading-header-lines)）：以空白或 tab 開頭的行用一個空白接上，其他的行或空行則結束這個值。0.1.0 把 CR 和 LF 當成值裡的字元：`attachment;\r\n filename=wire.pdf` 得不到檔名，`attachment; filename=a.pdf\r\nX-Note: 1` 則把下一行也吞進檔名；0.2.0 分別得到 `wire.pdf` 和 `a.pdf`。不含 CR 或 LF 的值不受這項改動影響。
- `content_type` 照 Chrome 網路層讀 Content-Type 標頭的方式來讀（見 [MIME 類型](behavior.md#the-mime-type)）：類型到第一個空白、tab、`;` 或 `(` 為止；有好幾個以逗號分隔的值時，最後一個有類型的值勝出，`*/*` 這個值本身則不改變結果。所以網址是 `https://example.com/page` 時，`text/html(comment)`、`text/html charset=utf-8` 和 `text/plain, text/html` 都得到 `page.html`，0.1.0 則是 `page`。
- feed 類型 `application/rss+xml` 和 `application/atom+xml` 跟 Chrome 一樣當成 `text/plain`：得到 `page.txt`，0.1.0 則分別是 `page.rss` 和 `page`。
- Chrome 只對 `http:`、`https:`、`file:` 和 `filesystem:` 網址檢查內容來決定 MIME 類型。網址是其他 scheme 的合法網址時，例如 `ftp://example.com/page`，沒有給出類型的 `content_type`（例如空字串）就是 `text/plain`：得到 `page.txt`，0.1.0 則是 `page`。

**`content_type` 是原樣的標頭。** 0.1.0 的文件說，伺服器沒有送出 `X-Content-Type-Options: nosniff` 時，要傳入 Chrome 會用的 MIME 類型，因為 Chrome 這時可能檢查內容、改用別的類型。0.2.0 撤回這個建議：`content_type` 是伺服器送出的原樣 Content-Type 標頭；Chrome 會檢查內容時，本套件看不到內容，用的是標頭宣告的類型。以來自 `https://example.com/page`、沒有 Content-Type、內容是 HTML 的回應為例，照舊的建議要傳 `mime_type="text/html"`，得到 `page.html`；0.2.0 對這組標頭給出 `page`，而 Chrome 回報的是 `page.html`（見 [Chrome 檢查內容時](usage.md#when-chrome-sniffs-the-body)）。

**改傳整組標頭。** 從傳單一個標頭改成傳全部的標頭，檔名可能改變：

- `X-Content-Type-Options: nosniff` 會算數。有它時 Chrome 不檢查內容，沒有 Content-Type、或 Content-Type 沒有給出類型的回應就是 `text/plain`：`https://example.com/page` 得到 `page.txt`，0.1.0 則是 `page`。
- 每一行 Content-Type 都算數：最後一個有類型的值勝出，`*/*` 這個值本身則不改變結果。`urllib.request` 和 aiohttp 依名稱取標頭時只給第一行：遇到 `text/plain` 和 `application/pdf` 兩行時，0.1.0 依第一行得到 `page.txt`，0.2.0 依兩行得到 `page.pdf`。
- 檔名跟以前一樣取自第一行 Content-Disposition 的第一個值。requests、httpx 和 httpx2 的 `response.headers` 會把好幾行接成一行，結果可能跟分開的各行不同（見[接成一行的標頭與推測的位元組](usage.md#joined-lines-and-guessed-bytes)）。

## 0.1.0

- 首次發布，跟隨 Chromium `dfd5cca812cefda32e909ae39965ed22041d5e65`（main，2026-10-16）及其 ICU 78。
- `suggested_filename()` 回傳 Chromium 替一次下載建議的檔名，`parse_content_disposition()` 照 Chromium 的方式讀取 Content-Disposition 標頭。兩者都接受位元組或字串形式的標頭。
- 純 Python、沒有相依套件，支援 CPython 3.11 以上和 PyPy。
