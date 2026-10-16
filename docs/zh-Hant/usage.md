# 使用方式

## 替下載命名 {#name-a-download}

`suggested_filename` 不會下載任何東西。照常用你的 HTTP 函式庫發出請求，再把回應提供的資訊交給它：Content-Disposition 標頭和回應的網址。使用串流回應時，讀取回應內容之前就拿得到這兩項。

```pycon
>>> from browser_download_filename import parse_content_disposition, suggested_filename
>>> suggested_filename(content_disposition='attachment; filename="Q3 report.pdf"')
'Q3 report.pdf'
>>> suggested_filename(
...     url="https://example.com/files/report.pdf",
...     content_disposition='attachment; filename="Q3 report.pdf"',
... )
'Q3 report.pdf'
>>> suggested_filename(
...     url="https://example.com/files/report.pdf?id=1", content_disposition="attachment"
... )
'report.pdf'
>>> suggested_filename(content_disposition="attachment")
'download'
```

Chrome 依下列順序，採用第一個提供檔名的來源：

1. `content_disposition`，也就是 Content-Disposition 標頭，或 `headers` 裡的 Content-Disposition 行（見[有多個 Content-Disposition 標頭時](#several-content-disposition-headers)）；回應沒有這個標頭時，兩者都省略；
2. `download_attribute`，也就是 `<a download>` 屬性的值（見 [download 屬性](#the-download-attribute)）；
3. `url`，也就是網址：取路徑的最後一段，解開百分比編碼，不含查詢字串（`about:` 和 `data:` 網址取不到檔名）；
4. `default_name`，沒有另外指定時是 `download`（見 [預設檔名](#the-default-name)）。

`url` 是回應的最終網址（跟隨重新導向之後的網址）。只有標頭沒有提供檔名時才會用到它，例如回應沒有 Content-Disposition、標頭裡既沒有 `filename` 也沒有 `filename*`，或是裡面的檔名無法解碼（見 [解碼舊式字元集](#decode-legacy-charsets)）。沒有網址時省略它，這時會跳過網址，接著用 `default_name`。檔名取自帶查詢字串的網址時，回應的 MIME 類型也可能換掉它的副檔名（見 [依 Content-Type 補副檔名](#add-an-extension-from-the-content-type)）。

回傳值一定是一個非空的檔名：不含 `/`、`\`、控制字元或其他檔案系統不接受的字元，開頭和結尾也不會是 `.` 或空白。把它放進你要的目錄即可：

```python
from pathlib import Path

path = Path(download_dir) / name
```

本套件只建議檔名，不會碰檔案系統。有兩件事要你自己處理：檔名可能超過檔案系統允許的長度（例如 Linux 的 ext4 每個檔名最多 255 個位元組，以 UTF-8 寫中文大約 85 個字）；同名檔案也可能已經存在（Chrome 會把新檔編號成 `report (1).pdf`）。

## 從 HTTP 函式庫傳入標頭 {#pass-the-header-from-your-http-library}

Chromium 讀的是標頭的原始位元組。Python 的 HTTP 函式庫會先把標頭解碼成字串，而且各家做法不同，所以能傳位元組時，就傳位元組。

requests、urllib3、`urllib.request` 和 `http.client` 一律用 Latin-1 解碼標頭；把字串再用 Latin-1 編碼回去，就能原封不動地拿回原始位元組：

```python
import requests
from browser_download_filename import suggested_filename

response = requests.get(url)
header = response.headers.get("Content-Disposition")
name = suggested_filename(
    url=response.url,
    content_disposition=header.encode("latin-1") if header is not None else None,
)
```

httpx 和 httpx2 都用同一種編碼解碼一個回應的所有標頭，並且告訴你是哪一種。它們預設不跟隨重新導向，`response.url` 也是 URL 物件而不是字串。使用串流回應時，先決定檔名，再讀取回應內容。httpx2 的寫法相同，只要把 `httpx` 換成 `httpx2`：

```python
from pathlib import Path

import httpx
from browser_download_filename import suggested_filename

with httpx.stream("GET", url, follow_redirects=True) as response:
    response.raise_for_status()
    header = response.headers.get("Content-Disposition")
    name = suggested_filename(
        url=str(response.url),
        content_disposition=(
            header.encode(response.headers.encoding) if header is not None else None
        ),
    )
    with open(Path(download_dir) / name, "wb") as file:
        for chunk in response.iter_bytes():
            file.write(chunk)
```

aiohttp 用 UTF-8 解碼標頭，解不了的位元組以 surrogate escape 保留；本套件會把它們轉回原本的位元組，所以 aiohttp 的字串可以直接傳入：

```python
async with session.get(url) as response:
    name = suggested_filename(
        url=str(response.url),
        content_disposition=response.headers.get("Content-Disposition"),
    )
```

在其他情況下傳字串也可以，只要標頭是 ASCII 或 UTF-8，而絕大多數標頭都是：如果字串裡全是 Latin-1 字元，而且這些字元的 Latin-1 位元組是合法的 UTF-8，就當成那些位元組來讀；其他字串則以 UTF-8 編碼。只有含舊式字元集位元組的標頭（例如 Windows-1252 的 `caf\xe9.txt`）從字串傳入時結果會不同，因為字串無法分辨那些位元組和一般文字。把你的 HTTP 函式庫解碼標頭時用的 codec 傳給 `headers_encoding`，字串就能精確還原成原本的位元組（見[以字串傳入時](api-reference.md#inputs-as-str)）。

### 有多個 Content-Disposition 標頭時 {#several-content-disposition-headers}

一個回應可能送出不只一次 Content-Disposition：分成好幾行標頭，或在同一行裡用逗號接起好幾個值。Chromium 會在引號外的逗號處切開每一行，用第一個值決定檔名。只要有任何一個值跟第一個值不同，Chrome 就會拒絕整個回應（`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`）。只有一個標頭、但引號外有逗號時也會這樣，例如 `attachment; filename=a,b.txt`。

把整組標頭交給本套件，它才看得到所有的值。依名稱取標頭時，requests、httpx 和 httpx2 會用 `, ` 把重複的標頭接起來，`urllib.request` 和 aiohttp 則只回傳第一個。把 `response.headers` 當成 `suggested_filename` 的第一個引數傳入，或傳給 `parse_content_disposition`；後者的 `blocks_download` 會告訴你 Chrome 會不會拒絕這個回應：

```pycon
>>> headers = [
...     ("Content-Disposition", 'attachment; filename="a.pdf"'),
...     ("Content-Disposition", 'attachment; filename="b.pdf"'),
... ]
>>> parse_content_disposition(headers)
ContentDisposition(type='attachment', filename='a.pdf', blocks_download=True)
>>> suggested_filename(headers, url="https://example.com/get")
'a.pdf'
>>> parse_content_disposition("attachment; filename=a,b.txt")
ContentDisposition(type='attachment', filename='a', blocks_download=True)
```

Chrome 拒絕一個回應時，指向它的一般連結什麼都不會下載：Chrome 改為顯示錯誤頁面。有 `download` 屬性的連結則仍會開始一個下載，而這個下載會失敗；Chrome 給它的名字取自該屬性或網址，不看回應的 Content-Disposition 和 Content-Type。`suggested_filename` 不模擬這種拒絕：它照樣用第一個值決定檔名，上面的例子是 `a.pdf`。

## 依 Content-Type 補副檔名 {#add-an-extension-from-the-content-type}

檔名不是取自 Content-Disposition 時，Chrome 會加上回應的 MIME 類型的副檔名，或修正檔名原有的副檔名。把回應的標頭交給本套件，它就照 Chrome 的方式從中讀出 MIME 類型：

```pycon
>>> headers = [("Content-Type", "application/pdf")]
>>> suggested_filename(headers, url="https://example.com/report")
'report.pdf'
>>> suggested_filename(headers, url="https://example.com/get.php?id=1")
'get.pdf'
>>> suggested_filename(headers, url="https://example.com/get.php")
'get.php'
>>> suggested_filename(
...     [*headers, ("Content-Disposition", 'attachment; filename="report"')],
...     url="https://example.com/x",
... )
'report'
```

- 沒有副檔名的檔名，會加上該 MIME 類型常用的副檔名。
- 網址帶查詢字串時，Chrome 認為檔案是由程式產生的，所以取自這種網址的檔名，副檔名會被換掉，除非它本來就是該 MIME 類型的副檔名之一。
- 取自 Content-Disposition 的檔名，副檔名維持原樣；原本沒有就不會加上。
- `; charset=utf-8` 這類參數會被忽略；`application/octet-stream` 和 Chromium 不知道副檔名的 MIME 類型也一樣。
- RSS 和 Atom feed 會得到 `.txt`；沒有 Content-Type、但送出 `X-Content-Type-Options: nosniff` 的回應也是。

本套件照 Chrome 網路層的方式讀取每一行 Content-Type，以及 X-Content-Type-Options（見 [MIME 類型](behavior.md#the-mime-type)）。要在標頭之外另外給 Content-Type，或根本沒有標頭時，把它的原始值傳給 `content_type`，可以是位元組，或 HTTP 函式庫解碼出的字串。它會取代 `headers` 裡所有的 Content-Type 行；預設的 `None` 表示沿用那些行。空字串代表一個空的 Content-Type，不是沒有傳。X-Content-Type-Options 只從 `headers` 讀取；`headers` 和 `content_type` 都沒有時，不使用任何 MIME 類型：

```pycon
>>> headers = [("Content-Type", "application/pdf"), ("X-Content-Type-Options", "nosniff")]
>>> suggested_filename(headers, url="https://example.com/report", content_type="text/html")
'report.html'
>>> suggested_filename(headers, url="https://example.com/report", content_type="")
'report.txt'
>>> suggested_filename(url="https://example.com/report", content_type="application/pdf")
'report.pdf'
```

### Chrome 檢查內容時 {#when-chrome-sniffs-the-body}

除非回應送出 `X-Content-Type-Options: nosniff`，否則 Content-Type 沒有給或提供的資訊太少時（`text/plain`、`application/octet-stream`、XML、Microsoft Office 類型和未知的類型），Chrome 會檢查內容的開頭（MIME sniffing），可能改用跟標頭不同的 MIME 類型。本套件看不到內容，所以用標頭宣告的類型，得到的檔名可能跟 Chrome 和 Playwright 回報的不同：沒有 Content-Type、內容是 HTML 的回應，在 Chrome 是 `page.html`，在本套件則是 `page`。要精確預測檔名，就讓實際的回應送出 `X-Content-Type-Options: nosniff`、改用 Chrome 不檢查內容的類型，或在 Content-Disposition 裡給出檔名。

這涵蓋的是 Chrome 經由網路載入的下載。其他載入回應的方式，例如 Playwright 的 `route.fulfill`，以及 `blob:`、`data:`、`file:` 網址，都沒有模擬；它們可能得到不同的 MIME 類型。

## 解碼舊式字元集 {#decode-legacy-charsets}

`filename` 裡不是 UTF-8 的原始位元組，或網址裡百分比編碼後不是 UTF-8 的位元組，本身都沒有標明字元集。Chrome 會用瀏覽器的「預設文字編碼」來解碼，這個設定跟著瀏覽器的語言走：英文是 windows-1252，正體中文是 Big5，簡體中文是 GBK，日文是 Shift_JIS，依此類推。DevTools 和 Playwright 不用任何備援編碼，本套件預設也不用；這時 Linux 上的 Chromium 會丟掉這個檔名，改用網址。要得到 Chrome 實際存檔的檔名，就把這個編碼傳給 `fallback_charset`：

```pycon
>>> header = b'attachment; filename="caf\xe9.txt"'
>>> suggested_filename(url="https://example.com/get", content_disposition=header)
'get'
>>> suggested_filename(
...     url="https://example.com/get", content_disposition=header, fallback_charset="windows-1252"
... )
'café.txt'
>>> suggested_filename(url="https://example.com/%A4%A4%A4%E5.txt", fallback_charset="big5")
'中文.txt'
```

編碼名稱必須是 Chromium 接受的標籤，也就是 [WHATWG Encoding Standard](https://encoding.spec.whatwg.org/#names-and-labels) 列出的那些；其他名稱（例如 `utf-7`）會丟出 `LookupError`。跟瀏覽器一樣，`iso-8859-1`、`latin1` 和 `us-ascii` 都代表 windows-1252。

## Windows {#windows}

`platform` 決定採用 Chrome 在 Linux、macOS 等 POSIX 系統上的規則（`"posix"`），或在 Windows 上的規則（`"windows"`）。預設跟著執行中的作業系統：在 Windows 上用 Windows 的規則，在其他系統上用 POSIX 的規則。要讓同樣的輸入不論在哪裡執行都得到同樣的檔名，就明確傳入 `platform="posix"` 或 `platform="windows"`，例如檔案會存到另一台機器上時：

```pycon
>>> suggested_filename(content_disposition='attachment; filename="con.txt"', platform="posix")
'con.txt'
>>> suggested_filename(content_disposition='attachment; filename="con.txt"', platform="windows")
'_con.txt'
>>> suggested_filename(content_disposition='attachment; filename="report.pdf..."', platform="windows")
'report.pdf___'
>>> suggested_filename(content_disposition='attachment; filename="invoice.pdf.lnk"', platform="windows")
'invoice.pdf.download'
```

在 Windows 上，Chrome 還會：

- 在保留的裝置名稱（`CON`、`PRN`、`AUX`、`NUL`、`COM1`–`COM9`、`LPT1`–`LPT9`、`CLOCK$`，有沒有副檔名都算）以及 `desktop.ini`、`thumbs.db`、`CONIN$`、`CONOUT$` 前面加上 `_`；
- 把結尾的 `.` 和空白換成 `_`，因為 Windows 會把它們去掉；
- 副檔名是 Windows 當成捷徑或 shell 物件的（`.lnk`、`.local`、`.scf`、`.url` 和 `{CLSID}` 形式的副檔名），改成 `.download`；
- 檔名可能是 8.3 短檔名時（例如 `REPORT~1.PDF`），把其中的 `~` 換掉。

## download 屬性 {#the-download-attribute}

`<a download="...">` 屬性的值就是 `download_attribute`。Content-Disposition 裡的檔名優先於它，網址則排在它後面：

```pycon
>>> suggested_filename(url="https://example.com/files/1234", download_attribute="notes.txt")
'notes.txt'
>>> suggested_filename(
...     url="https://example.com/files/1234",
...     content_disposition='attachment; filename="server.txt"',
...     download_attribute="notes.txt",
... )
'server.txt'
```

連結指向其他來源（origin）時，Chrome 會忽略這個屬性；所以只在連結指向同一來源，或是 `data:`、`blob:` 網址時傳入它。

## 預設檔名 {#the-default-name}

`default_name` 用在沒有任何地方提供檔名，或取得的檔名只由 `-` 和 `_` 組成的時候。`download` 是 DevTools 使用的預設檔名。`default_name=None` 時，沒有任何地方提供檔名就改用網址的主機名稱（如果有的話），其他情況用 `download`。`default_name` 傳入空字串會丟出 `ValueError`。

```pycon
>>> suggested_filename(url="https://example.com/", default_name="untitled")
'untitled'
>>> suggested_filename(url="https://example.com/", default_name=None)
'example.com'
```

## 清洗任意名稱 {#sanitize-a-name}

`sanitize_filename` 把 Chrome 的清洗規則套用在其他來源的名稱上，例如網頁標題或使用者輸入。它清洗名稱的方式跟 Chrome 清洗 `<a download>` 屬性的值相同，所以拿來存檔跟 `suggested_filename` 的結果一樣安全：

```pycon
>>> from browser_download_filename import sanitize_filename
>>> sanitize_filename("Q3 report: draft?.pdf")
'Q3 report_ draft_.pdf'
>>> sanitize_filename("季度報告.pdf")
'季度報告.pdf'
>>> sanitize_filename("../../etc/passwd")
'_.._etc_passwd'
>>> sanitize_filename("con.txt", platform="windows")
'_con.txt'
>>> sanitize_filename("...", default_name="untitled")
'untitled'
```

`default_name` 和 `platform` 的用法跟 `suggested_filename` 相同，只是 `default_name` 不能是 `None`：這裡沒有網址可以取主機名稱。

## 只解析標頭 {#parse-a-header}

`parse_content_disposition` 只回傳處置類型和檔名，不做後續的命名步驟：

```pycon
>>> cd = parse_content_disposition('attachment; filename="../../etc/passwd"')
>>> cd.type, cd.is_attachment
('attachment', True)
>>> cd.filename
'../../etc/passwd'
>>> parse_content_disposition("inline")
ContentDisposition(type='inline', filename=None, blocks_download=False)
>>> parse_content_disposition(None)
ContentDisposition(type='inline', filename=None, blocks_download=False)
```

這裡的檔名已經解碼，但沒有清洗：它可能含有路徑分隔符號、控制字元，以及伺服器送來的任何東西。絕對不要直接拿它當路徑；要存檔用的檔名，請用 `suggested_filename`。`inline` 和 `attachment` 以外的處置類型都算 `attachment`，跟 Chromium 一樣。

## 取代其他解析器 {#replacing-another-parser}

| 原本 | 改成 |
| --- | --- |
| `pyrfc6266.parse_filename(header)` | `parse_content_disposition(header).filename` |
| `email.message.Message.get_filename()` | `parse_content_disposition(header).filename` |
| 自己寫的網址備援與檔名清洗 | `suggested_filename(url=url, content_disposition=header)` |
| 自己寫的、清洗其他來源名稱的程式 | `sanitize_filename(name)` |

`parse_content_disposition` 遇到格式錯誤的標頭不會丟出例外，沒有可用的檔名時回傳 `None`。凡是 Chromium 跟嚴格照 RFC 的解析器結果不同的地方，本套件都跟著 Chromium，這正是它的用意。
