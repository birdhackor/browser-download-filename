# 總覽

browser-download-filename 照 Chrome 的方式替下載的檔案命名。它是 Chromium（Chrome、Edge 等瀏覽器共用的開放原始碼核心）兩個部分的純 Python 移植：Content-Disposition 標頭的解析器（`net::HttpContentDisposition`），以及依回應決定下載檔名的函式（`net::GetSuggestedFilename`）。

## 快速開始 {#quick-start}

```console
python -m pip install browser-download-filename
```

```pycon
>>> from browser_download_filename import suggested_filename
>>> header = b"attachment; filename=report.pdf; filename*=UTF-8''%E5%A0%B1%E5%91%8A.pdf"
>>> headers = [("Content-Disposition", header)]
>>> suggested_filename(headers, url="https://example.com/download?id=42")
'報告.pdf'
```

結果就是 Chrome 回報給 DevTools 和 Playwright 的「建議檔名」，也是可以直接拿來存檔的安全檔名。從 httpx2、httpx、requests、aiohttp 和 `urllib.request` 傳入標頭的寫法，見[使用方式](usage.md)。

## 為什麼需要它 {#why}

程式用 HTTP 函式庫下載檔案時，檔名要由程式自己決定。伺服器建議的檔名放在 Content-Disposition 標頭裡，而伺服器的寫法五花八門，很多是標準不允許、但瀏覽器照樣接受的。照標準讀這個標頭的程式，就會把這些檔名弄錯。以 Python 標準庫的 `email` 模組為例：

| Content-Disposition | Chrome 與本套件 | `email.message.Message.get_filename()` |
| --- | --- | --- |
| `attachment; filename="fallback.zip"; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip` | `中文.zip` | `fallback.zip` |
| `attachment; filename="%E4%B8%AD%E6%96%87.zip"` | `中文.zip` | `%E4%B8%AD%E6%96%87.zip` |
| `attachment; filename="=?UTF-8?B?5Lit5paHLnppcA==?="` | `中文.zip` | `=?UTF-8?B?5Lit5paHLnppcA==?=` |
| 以原始 UTF-8 送出的 `attachment; filename="中文.zip"`，經 requests 讀取 | `中文.zip` | `'ä¸\xadæ\x96\x87.zip'` |

這類標頭該怎麼處理，也沒有標準可依：HTML 標準只說依 RFC 6266，各瀏覽器共用的測試集 web-platform-tests 也沒有任何檔名解析的測試。格式正確的標頭，各瀏覽器結果一致；其餘的各有做法。Chrome 是使用者最多的瀏覽器，所以本套件以它為準；Firefox 和 Safari 哪裡不同，見[行為與瀏覽器差異](behavior.md)。

標頭裡的檔名只是第一步。Chrome 在標頭沒有檔名時改用網址，再不行就叫 `download`，最後還會清洗選出來的檔名：路徑分隔符號、控制字元和其他檔案系統不接受的字元都會被替換，開頭和結尾的 `.` 會被去掉，所以 `../../etc/passwd` 會變成 `_.._etc_passwd`。`suggested_filename` 把這些步驟全部做完。

## 提供什麼 {#what-you-get}

| 函式 | 用途 |
| --- | --- |
| `suggested_filename(headers, url=..., ...)` | Chrome 替一次下載取的檔名：依序從 Content-Disposition、`<a download>` 的值、網址或預設名取得，再清洗；不是取自 Content-Disposition 的檔名，可能依 MIME 類型補上副檔名。Content-Disposition 和 MIME 類型取自回應的標頭，或 `content_disposition=` 與 `content_type=`；`platform=` 選擇 Chrome 在 Windows 或 POSIX 上的規則。 |
| `sanitize_filename(name)` | 把 Chrome 的清洗規則套用在任何來源的名稱上，例如網頁標題或使用者輸入，清洗方式跟 Chrome 清洗 `<a download>` 的值相同。 |
| `parse_content_disposition(value)` | 照 Chromium 的方式讀出標頭的處置類型和解碼後的檔名，不做清洗；也告訴你 Chrome 會不會因為 Content-Disposition 的值彼此不同而拒絕這個回應。 |

`suggested_filename` 和 `parse_content_disposition` 都可以傳入回應的整組標頭，或單一個位元組（bytes）或字串（str）形式的標頭，遇到格式錯誤的標頭不會丟出例外。本套件除了標準庫之外沒有任何相依套件，支援 CPython 3.11 以上和 PyPy。

## 有多精確 {#how-exact-it-is}

標頭解析、字元集解碼和檔名規則，都是從釘選版本的 Chromium 原始碼移植過來的，Chromium 自己的單元測試案例也是本套件測試的一部分。CI 還會用真正的 Chromium 下載 800 多個案例：檔名由標頭和網址決定的案例，要求每一個都完全相同；Chrome 會檢查內容來決定 MIME 類型的案例，則改為檢查逐案列出的檔名。測試的細節見[如何驗證](verification.md)；Chrome 還做了哪些事、本套件交給你自己處理（例如檔案已存在時替新檔編號），見[行為與瀏覽器差異](behavior.md)。

下一步：範例在[使用方式](usage.md)，完整的 API 在 [API 參考](api-reference.md)。
