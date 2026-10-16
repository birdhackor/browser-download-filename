# API 參考

以下所有名稱都可以從 `browser_download_filename` 匯入。範例見[使用方式](usage.md)。

## suggested_filename {#suggested_filename}

```python
def suggested_filename(
    *,
    url: str | None = None,
    content_disposition: str | bytes | None = None,
    content_type: str | bytes | None = None,
    download_attribute: str | None = None,
    default_name: str | None = "download",
    fallback_charset: str | None = None,
    platform: Literal["posix", "windows"] | None = None,
) -> str
```

Chromium 替一次下載建議的檔名（`net::GetSuggestedFilename`），也就是 Chrome 回報給 DevTools 和 Playwright 的檔名。一定不是空字串。

| 參數 | 意義 |
| --- | --- |
| `url` | 回應的最終網址（跟隨重新導向之後）；沒有網址時傳 `None`。只在 Content-Disposition 和 `download_attribute` 都沒有提供檔名時使用：取路徑的最後一段（`about:` 和 `data:` 網址取不到）；取不到而且 `default_name` 是 `None` 時，改用主機名稱。 |
| `content_disposition` | Content-Disposition 標頭，可以是位元組，或 HTTP 函式庫解碼出的字串；回應沒有這個標頭時傳 `None`。只使用它以逗號分隔的第一個值。 |
| `content_type` | 回應的 Content-Type，可以是字串或位元組（位元組以 Latin-1 解讀），參數會被忽略。檔名不是取自 Content-Disposition 時，用它補上或修正副檔名。 |
| `download_attribute` | `<a download>` 屬性的值。Content-Disposition 沒有提供檔名時使用。 |
| `default_name` | 沒有任何地方提供檔名時使用的名稱，不能是空字串。若為 `None`，先嘗試網址的主機名稱，最後才用 `download`。 |
| `fallback_charset` | 用來解碼 `filename` 和網址路徑裡非 UTF-8 原始位元組的字元集；Chrome 在這裡用的是瀏覽器的預設文字編碼。必須是 Chromium 認得的標籤，例如 `"windows-1252"` 或 `"big5"`。 |
| `platform` | `"posix"` 採用 Chrome 在 Linux、macOS 等 POSIX 系統上的規則，`"windows"` 採用它在 Windows 上的規則。預設的 `None` 在 Windows 上執行時（`sys.platform == "win32"`）選 `"windows"`，其他系統選 `"posix"`。 |

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

## parse_content_disposition {#parse_content_disposition}

```python
def parse_content_disposition(
    value: str | bytes | None,
    *,
    fallback_charset: str | None = None,
) -> ContentDisposition
```

照 Chromium 的 `net::HttpContentDisposition` 解析 Content-Disposition 標頭。`value` 是位元組形式的標頭，或 HTTP 函式庫解碼出的字串；`None` 代表沒有這個標頭。只使用它以逗號分隔的第一個值。`fallback_charset` 同上。

## ContentDisposition {#contentdisposition}

```python
@dataclass(frozen=True, slots=True)
class ContentDisposition:
    type: Literal["inline", "attachment"]
    filename: str | None

    @property
    def is_attachment(self) -> bool: ...
```

解析後的標頭：不可變的值，依欄位比較相等與計算雜湊。

| 屬性 | 意義 |
| --- | --- |
| `type` | `attachment`，以及 Chromium 不認得的其他合法處置類型，都是 `"attachment"`；`inline`、沒有標頭，或標頭不是以合法類型開頭時，是 `"inline"`。 |
| `filename` | 解碼後的檔名；標頭裡沒有 Chromium 能用的檔名時是 `None`。它沒有經過清洗：可能含有路徑分隔符號、控制字元，以及其他放在檔名裡不安全的字元。 |
| `is_attachment` | `type` 是否為 `"attachment"`。 |

## `__version__`

已安裝的套件版本，型別是字串。

## 例外 {#exceptions}

格式錯誤的標頭和網址都不會丟出例外，只有不合法的引數會。

| 例外 | 發生時機 |
| --- | --- |
| `LookupError` | `fallback_charset` 不是 Chromium 能解碼的字元集，例如 `utf-7`。 |
| `TypeError` | 標頭或 `content_type` 不是字串、位元組或 `None`；`url`、`download_attribute`、`fallback_charset` 或 `suggested_filename` 的 `default_name` 不是字串或 `None`；或 `name`、`sanitize_filename` 的 `default_name` 不是字串。 |
| `ValueError` | `platform` 不是 `"posix"`、`"windows"` 或 `None`；或 `default_name` 是空字串。 |

## 以字串傳入時 {#inputs-as-str}

Chromium 把標頭當成位元組來讀，所以字串會先轉回位元組。如果每個字元都在 U+0000–U+00FF 之間，而且它們的 Latin-1 位元組是合法的 UTF-8，就使用這些位元組；requests、urllib3、`http.client` 和 WSGI 把帶有 UTF-8 的標頭交給你時，正是這種字串。其他字串一律以 UTF-8 編碼，並把 aiohttp 用來保留無法解碼位元組的 surrogate escape 轉回原本的位元組。網址和其他字串參數則當成文字處理；其中落單的 surrogate 會變成 U+FFFD。
