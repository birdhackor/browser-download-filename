# API 參考

以下所有名稱都可以從 `browser_download_filename` 匯入。範例見[使用方式](usage.md)。

## suggested_filename {#suggested_filename}

```python
def suggested_filename(
    headers: HeadersLike | None = None,
    *,
    url: str | None = None,
    content_disposition: str | bytes | None = None,
    content_type: str | bytes | None = None,
    download_attribute: str | None = None,
    default_name: str | None = "download",
    fallback_charset: str | None = None,
    headers_encoding: str | None = None,
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

Chromium 替一次下載建議的檔名（`net::GetSuggestedFilename`），也就是 Chrome 回報給 DevTools 和 Playwright 的檔名，[移植的限制](behavior.md#limits-of-the-port)列出的情況除外。一定不是空字串。

| 參數 | 意義 |
| --- | --- |
| `headers` | 回應的標頭（見 [`HeadersLike`](#headerslike)）；沒有時傳 `None`。從中讀取三個標頭：Content-Disposition，取第一行以逗號分隔的第一個值；每一行 Content-Type，用來決定 MIME 類型；X-Content-Type-Options，它的第一個值決定 Chrome 會不會檢查內容、改用別的 MIME 類型（見 [MIME 類型](behavior.md#the-mime-type)）。 |
| `url` | 回應的最終網址（跟隨重新導向之後）；沒有網址時傳 `None`。Content-Disposition 和 `download_attribute` 都沒有提供檔名時，檔名取自路徑的最後一段（`about:` 和 `data:` 網址取不到）；取不到而且 `default_name` 是 `None` 時，改用主機名稱。有 `headers` 或 `content_type` 時，它的 scheme 也決定 Chrome 能不能檢查內容來決定 MIME 類型：只有 `http:`、`https:`、`file:` 和 `filesystem:` 網址的內容會被檢查；`url` 是 `None` 時，本套件當成是其中之一（見 [MIME 類型](behavior.md#the-mime-type)）。 |
| `content_disposition` | Content-Disposition 標頭，可以是位元組，或 HTTP 函式庫解碼出的字串。預設的 `None` 表示從 `headers` 讀取（有傳的話）。其他任何值都會取代 `headers` 裡所有的 Content-Disposition 行，空字串也一樣：要忽略伺服器給的檔名，就傳 `""`。只使用它以逗號分隔的第一個值。 |
| `content_type` | Content-Type 標頭，可以是位元組，或 HTTP 函式庫解碼出的字串。預設的 `None` 表示從 `headers` 讀取（有傳的話）。其他任何值都會取代 `headers` 裡所有的 Content-Type 行；空字串代表一個空的 Content-Type。檔名不是取自 Content-Disposition 時，用 MIME 類型補上或修正副檔名；`headers` 和 `content_type` 都沒有時，不使用任何 MIME 類型。`"application/octet-stream"` 不會補上或修正副檔名（見[不理會 Content-Type](usage.md#ignore-the-content-type)）。 |
| `download_attribute` | `<a download>` 屬性的值。Content-Disposition 沒有提供檔名時使用。 |
| `default_name` | 沒有任何地方提供檔名時使用的名稱，不能是空字串。若為 `None`，先嘗試網址的主機名稱，最後才用 `download`。 |
| `fallback_charset` | 用來解碼 `filename` 和網址路徑裡非 UTF-8 原始位元組的字元集；Chrome 在這裡用的是瀏覽器的預設文字編碼。必須是 Chromium 認得的標籤，例如 `"windows-1252"` 或 `"big5"`。 |
| `headers_encoding` | 你的 HTTP 函式庫把標頭解碼成字串時用的 Python codec，例如 requests 是 `"latin-1"`，httpx 是 `response.headers.encoding`。`headers`、`content_disposition` 和 `content_type` 裡每一個字串形式的標頭值，都用它編碼回位元組；位元組則原樣使用。`None` 表示改用推測的方式還原位元組（見[以字串傳入時](#inputs-as-str)）。這是 Python 的 codec 名稱，不是字元集標籤：這裡的 `"latin-1"` 是 ISO-8859-1，不是 windows-1252。 |
| `platform` | `"posix"` 採用 Chrome 在 Linux、macOS 等 POSIX 系統上的規則，`"windows"` 採用它在 Windows 上的規則。預設的 `None` 在 Windows 上執行時（`sys.platform == "win32"`）選 `"windows"`，其他系統選 `"posix"`。它選的是 Chrome 的檔名規則，不包括系統的 MIME 類型對照（見[移植的限制](behavior.md#limits-of-the-port)）。 |

## sanitize_filename {#sanitize_filename}

```python
def sanitize_filename(
    name: str,
    *,
    default_name: str = "download",
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

把 Chrome 的檔名清洗規則套用在任何來源的名稱上，例如網頁標題或使用者輸入。結果等於 `suggested_filename(download_attribute=name, default_name=default_name, platform=platform)` 的回傳值：`name` 的清洗方式跟 Chrome 清洗 `<a download>` 屬性的值相同。一定不是空字串。

| 參數 | 意義 |
| --- | --- |
| `name` | 要清洗的名稱。 |
| `default_name` | `name` 沒有提供檔名時使用的名稱，跟 `suggested_filename` 相同。必須是非空字串。 |
| `platform` | 跟 `suggested_filename` 相同。 |

## HeadersLike {#headerslike}

```python
HeadersLike = SupportsHeaderItems | Iterable[tuple[str | bytes, HeaderValue]]
```

回應標頭的型別，涵蓋 HTTP 函式庫保存標頭的各種形狀：

- 有 `items()` 方法的物件（`SupportsHeaderItems`），例如 dict、`urllib.request` 以 `response.headers` 給出的 `http.client.HTTPMessage`、requests 以 `response.raw.headers` 給出的 urllib3 標頭物件，或 requests、httpx 和 httpx2 的 `response.headers`；本套件會呼叫 `items()`；
- 其他情況下，由 `(名稱, 值)` 配對組成的 iterable，例如由 tuple 組成的 list、httpx 和 httpx2 的 `response.headers.raw`，或 aiohttp 的 `response.raw_headers`。

名稱是字串或位元組，比對方式見[讀取標頭行](behavior.md#reading-header-lines)。值（`HeaderValue`）是字串或位元組，或由它們組成的 list 或 tuple（每個元素是一行標頭）。標頭行保持原本的順序，重複的行都會算進去。標頭只會被走訪一次，所以 generator 也可以。

每個值是該行標頭照送出時原樣的其餘部分。值裡可以有換行，照 Chrome 的方式讀：以空白或 tab 開頭的行會接上去，其他的行或空行則結束這個值（見[讀取標頭行](behavior.md#reading-header-lines)）。`content_disposition`、`content_type` 與 `parse_content_disposition` 收到的值也一樣。

字串或位元組不是標頭：`suggested_filename` 收到它會丟出 `TypeError`；單一個 Content-Disposition 值請傳給 `content_disposition`。

## parse_content_disposition {#parse_content_disposition}

```python
def parse_content_disposition(
    value: str | bytes | HeadersLike | None,
    /,
    *,
    fallback_charset: str | None = None,
    headers_encoding: str | None = None,
) -> ContentDisposition
```

照 Chromium 的 `net::HttpContentDisposition` 解析 Content-Disposition。`value` 是單一個標頭，可以是位元組，或 HTTP 函式庫解碼出的字串；也可以是回應的標頭（見 [`HeadersLike`](#headerslike)），這時會讀取其中每一行 Content-Disposition；`None` 代表沒有這個標頭。`type` 和 `filename` 取自第一行以逗號分隔的第一個值，也就是 Chrome 的下載程式碼讀取的那個值；`blocks_download` 則表示 Chrome 會不會因為這些值不同或標頭裡有 NUL 而拒絕這個回應。`fallback_charset` 和 `headers_encoding` 同上。

## ContentDisposition {#contentdisposition}

```python
@dataclass(frozen=True, slots=True)
class ContentDisposition:
    type: Literal["inline", "attachment"]
    filename: str | None
    blocks_download: bool = False

    @property
    def is_attachment(self) -> bool: ...
```

解析後的標頭：不可變的值，依欄位比較相等與計算雜湊。

| 屬性 | 意義 |
| --- | --- |
| `type` | `attachment`，以及 Chromium 不認得的其他合法處置類型，都是 `"attachment"`；`inline`、沒有標頭，或標頭不是以合法類型開頭時，是 `"inline"`。 |
| `filename` | 解碼後的檔名；標頭裡沒有 Chromium 能用的檔名時是 `None`。它沒有經過清洗：可能含有路徑分隔符號、控制字元，以及其他放在檔名裡不安全的字元。 |
| `blocks_download` | Chrome 是否因為以下兩種原因之一拒絕整個回應：把 Content-Disposition 的值在引號外的逗號處切開、去掉前後的空白和 tab 之後，只要不是每個值都逐位元組相同（`ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION`），或標頭裡有 NUL，不論在哪個標頭的名稱或值裡（`ERR_INVALID_HTTP_RESPONSE`；見[讀取標頭行](behavior.md#reading-header-lines)），就是 `True`。Chrome 拒絕回應的原因不只這兩種，其他原因不會讓它變成 `True`（見[移植的限制](behavior.md#limits-of-the-port)）。`type` 和 `filename` 仍取自第一個值。見[有多個 Content-Disposition 標頭時](usage.md#several-content-disposition-headers)。 |
| `is_attachment` | `type` 是否為 `"attachment"`。 |

## `__version__`

已安裝的套件版本，型別是字串。

## 例外 {#exceptions}

格式錯誤的標頭和網址都不會丟出例外，只有不合法的引數會。

| 例外 | 發生時機 |
| --- | --- |
| `LookupError` | `fallback_charset` 不是 Chromium 能解碼的字元集，例如 `utf-7`；或 `headers_encoding` 不是 Python 的文字 codec，例如 `rot13`。 |
| `TypeError` | `headers` 是字串或位元組；`headers` 或 `parse_content_disposition` 的 `value` 不是 [`HeadersLike`](#headerslike)：既不是 mapping 也不是 iterable、其中的項目不是 `(名稱, 值)` 配對，或名稱、值是其他型別；標頭的值或 `content_type` 不是字串、位元組或 `None`；`url`、`download_attribute`、`fallback_charset`、`headers_encoding` 或 `suggested_filename` 的 `default_name` 不是字串或 `None`；或 `name`、`sanitize_filename` 的 `default_name` 不是字串。 |
| `ValueError` | `platform` 不是 `"posix"`、`"windows"` 或 `None`；`default_name` 是空字串；或某個字串形式的標頭值無法用 `headers_encoding` 編碼，這代表標頭不是用這個 codec 解碼的。 |

以上都會在解析任何標頭之前檢查完畢，`headers` 裡的每一個標頭都包括在內。

## 以字串傳入時 {#inputs-as-str}

Chromium 把標頭當成位元組來讀，所以字串會先轉回位元組。有 `headers_encoding` 時，還原是精確的：用那個 codec 編碼字串，並把 surrogate escape 轉回它代表的位元組（`value.encode(headers_encoding, "surrogateescape")`）。

沒有它時，位元組是推測出來的。如果每個字元都在 U+0000–U+00FF 之間，而且它們的 Latin-1 位元組是合法的 UTF-8，就使用這些位元組；requests、urllib3 和 `http.client`（`urllib.request` 用的就是它）把帶有 UTF-8 的標頭交給你時，正是這種字串。其他字串一律以 UTF-8 編碼，並把 aiohttp 用來保留無法解碼位元組的 surrogate escape 轉回原本的位元組。推測可能出錯，例如 HTTP 函式庫以 Latin-1 解碼的舊式字元集位元組，像是 windows-1252 的 `caf\xe9.txt`。不過它不會改變 Content-Type 和 X-Content-Type-Options 的結果：只有 ASCII 字元可能對上某個 MIME 類型或 `nosniff`，而推測一定把它們還原成原本的位元組。

網址和其他字串參數則當成文字處理；其中落單的 surrogate 會變成 U+FFFD。
