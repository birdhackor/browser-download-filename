# 行為與瀏覽器差異

這一頁說明本套件遵循的規則（也就是 Chromium 的規則）、Chrome 在這之外還做了什麼，以及 Firefox 和 Safari 的命名哪裡不同。

## 讀取標頭行 {#reading-header-lines}

Chrome 先把回應的標頭當成收到的位元組來讀，之後才讀個別的標頭。本套件也用同樣的方式讀每一個標頭值：把它當成該行標頭在冒號之後、照送出時原樣的其餘部分。所以值裡可以有換行；HTTP 早已不建議在標頭裡換行：

- **空行結束標頭。** 一個 LF、可有可無的一個 CR，再接一個 LF，構成空行，之後的位元組是內容。
- **以空白或 tab 開頭的行延續這個標頭。** 換行和該行開頭的空白與 tab 換成一個空白接上去；前一行結尾的空白與 tab 保留。所以 `filename="a \r\n b.pdf"` 的檔名是 `a  b.pdf`，中間有兩個空白。
- **其他的行是另一行標頭**，所以這個值在它前面的換行處結束。只有 CR 和 LF 會換行：垂直 tab（VT）和換頁（FF）是值的一部分，也不會開始一個延續的行。
- **標頭裡任何地方有 NUL**（不論在名稱還是值裡），Chrome 就會拒絕整個回應（`ERR_INVALID_HTTP_RESPONSE`），就像它拒絕 Content-Disposition 的值彼此不同的回應一樣（見[讀取 Content-Disposition](#reading-content-disposition)）。`parse_content_disposition` 用 `blocks_download` 回報這種情況，`suggested_filename` 照樣決定檔名。空行之後的 NUL 屬於內容，不影響結果。

本套件一次讀一個值，所以值在線上構成的標頭行，並不是每一行都照 Chrome 的方式讀（見[移植的限制](#limits-of-the-port)）。

## 讀取 Content-Disposition {#reading-content-disposition}

- **只看第一個值。** 每一行 Content-Disposition 都會在引號外的逗號處切開，檔名取自第一行的第一個值。所以只要引號都有關上，重複的標頭不論是分成好幾行，還是被 HTTP 函式庫用 `, ` 接成一行，結果都一樣。沒關上的引號會一路延續到該行結尾，接成一行時就會吞進後面的值：`attachment; filename="a` 和 `attachment; filename=b` 兩行，檔名是 `a`，而且有兩個不同的值；接成一行則是單一個值，檔名是 `a, attachment; filename=b`。只要有任何一個值跟第一個值不同（去掉前後的空白和 tab 之後逐位元組比較），Chrome 就會拒絕整個回應，什麼都不下載；有 `download` 屬性的連結則會開始一個失敗的下載（見[使用方式](usage.md#several-content-disposition-headers)）。內容不同的重複標頭會這樣，只有一個標頭、但引號外有逗號時也會，例如 `filename=a,b.txt` 或結尾多一個逗號。`parse_content_disposition` 用 `blocks_download` 回報這種情況，標頭裡有 NUL 時也是（見[讀取標頭行](#reading-header-lines)）；`suggested_filename` 照樣用第一個值決定檔名。
- **處置類型。** `inline` 是 inline；`attachment` 和其他任何 token 都是 attachment。不是以 token 開頭的標頭（例如 `filename=report.pdf`）會整個當成參數來讀，類型是 inline，裡面的檔名照樣採用。
- **參數**由左到右讀，遇到第一個格式錯誤的參數就停止：沒有 `=`、值是空的，或名稱裡有引號。
- **`filename*` 優先**，不論出現順序，只要能解碼。它的值是 `charset'language'百分比編碼的位元組`（RFC 8187）：語言標記會被忽略；字元集可以是 Chromium 認得的任何一種（`UTF-8`、`ISO-8859-1`、`Shift_JIS`……）；位元組必須是該字元集的合法內容；結果會正規化成 NFC。無法解碼的 `filename*` 會被略過，改用 `filename`。
- **`filename`** 可以是 token 或加引號的字串，而且照瀏覽器的方式解碼，即使 RFC 不允許：
    - 原始 UTF-8 位元組照 UTF-8 解碼；
    - 百分比編碼會被解碼（`%E4%B8%AD%E6%96%87.zip` 是 `中文.zip`），解出來不是 UTF-8 時整個檔名作廢；
    - RFC 2047 的 encoded word 會被解碼（`=?UTF-8?B?5Lit5paHLnppcA==?=`）；
    - 其他原始位元組，有 `fallback_charset` 時用它解碼；沒有的話就丟掉（Linux 上的 Chrome 就是這樣），通常結果是沒有檔名。
- **不支援**（跟 Chromium 一樣）：RFC 2231 的分段寫法（`filename*0=`、`filename*1*=`），會被忽略。

## 選出檔名 {#picking-the-name}

`suggested_filename` 依序取下列第一個非空的結果：

1. Content-Disposition 裡的檔名，不論處置類型是什麼；
2. `download_attribute`，也就是 `<a download>` 的值；
3. 網址路徑的最後一段：最後一個 `/` 或 `\` 之後、`;` 之前的部分，並做百分比解碼。解出的位元組必須是 UTF-8，或能用 `fallback_charset` 解碼。`data:` 和 `about:` 網址，以及不合法的網址，都不提供檔名。
4. 網址的主機名稱，但只在 `default_name` 是 `None` 時。

## 清洗檔名 {#sanitizing-it}

接著依序：

1. 去掉開頭和結尾的 `.`（在 Windows 上，結尾的 `.` 和空白會先換成 `_`），並把 `/` 和 `\` 換成 `_`。
2. 如果這時檔名是空的，或只由 `-` 和 `_` 組成，就換成 `default_name`（沒有另外指定時是 `download`）；`default_name` 是 `None` 時換成 `download`。
3. 任何位置都不允許的字元換成 `_`：`"`、`*`、`/`、`:`、`<`、`>`、`?`、`\`、`|`、控制字元、Unicode 格式字元（例如由右至左覆寫字元 U+202E）以及非字元（noncharacter）。出現在開頭或結尾的空白、`.` 和 `~` 也換成 `_`。
4. 套用 MIME 類型的副檔名規則（見 [MIME 類型](#the-mime-type)）和 Windows 規則，說明見[使用方式](usage.md#add-an-extension-from-the-content-type)。

所以由 `report`、U+202E 和 `txt.exe` 組成、看起來像 `reportexe.txt` 的檔名，會變成 `report_txt.exe`。

## MIME 類型 {#the-mime-type}

副檔名取自 Chrome 網路層交給下載程式碼的 MIME 類型。本套件用同樣的方式，從 `headers` 和 `content_type` 推導出它；兩者都沒有時，不使用 MIME 類型。

- **Content-Type。** 所有 Content-Type 行用 `, ` 接起來，再在引號外的逗號處切開，所以某一行沒關上的引號會延續到下一行。每個值的類型從開頭算到第一個空白、tab、`;` 或 `(` 之前，而且必須包含該值的第一個 `/`。除此之外不做任何檢查，所以 `text/` 和 `"text/html"` 都算類型，只是沒有對應的副檔名。最後一個有類型的值決定 MIME 類型，並轉成 ASCII 小寫；沒有類型的值，以及剛好是 `*/*` 的值，不改變結果。所以 `text/plain, text/html` 是 `text/html`，`text/html, bogus` 是 `text/html`，`*/*; q=1` 則是 `*/*`。
- **檢查內容（sniffing）。** 類型沒有給、是 `text/plain`、`application/octet-stream`、`text/xml`、`application/xml`、Microsoft Office 類型，或是未知的類型（`unknown/unknown`、`application/unknown`、`*/*`）時，Chrome 會檢查內容、改用別的 MIME 類型；除非第一行 X-Content-Type-Options 的第一個值是 `nosniff`（不分 ASCII 大小寫）。Chrome 只檢查 `http:`、`https:`、`file:` 和 `filesystem:` 網址的內容；沒有傳 `url` 時，本套件當成會檢查。本套件看不到內容：Chrome 會檢查內容時，它用宣告的類型，或不用任何類型（見[使用方式](usage.md#when-chrome-sniffs-the-body)）。
- **不檢查內容時**，沒有類型就當成 `text/plain`；feed 類型 `application/rss+xml` 和 `application/atom+xml` 也換成 `text/plain`。

## Chrome 在這之外還做的事 {#what-chrome-does-beyond-this}

本套件回傳的是下載開始時，Chrome 回報給 DevTools 和 Playwright 的檔名；Chrome 檢查內容來決定 MIME 類型（見 [MIME 類型](#the-mime-type)），或拒絕這個回應（見[讀取 Content-Disposition](#reading-content-disposition)）時例外。Chrome 最後實際寫入的檔案，名稱可能不同：

- **預設文字編碼。** 遇到不是 UTF-8 的原始位元組，Chrome 會用瀏覽器的預設文字編碼解碼。請把它傳給 `fallback_charset`（見[使用方式](usage.md#decode-legacy-charsets)）。
- **已存在的檔案。** Chrome 會替檔名編號，例如 `report (1).pdf`。
- **過長的檔名。** 檔名超過檔案系統的長度上限時，Chrome 會截短它，並保留副檔名。
- **作業系統。** Windows 和 macOS 上的 Chrome 還會詢問系統某個 MIME 類型對應什麼副檔名；本套件只用 Chromium 內建的對照表，Linux 上的 Chrome 也只用這份。沒有預設編碼時，對不是 UTF-8 的原始檔名，Windows 上的 Chrome 用系統的 ANSI code page 解碼，macOS 上的 Chrome 把這些位元組換成 U+FFFD；本套件則跟 Linux 上的 Chrome 一樣把它們丟掉。ChromeOS 還會把檔名正規化成 NFC。
- **檔名以外的一切**：「另存新檔」對話框、安全瀏覽（Safe Browsing）與危險檔案警告、會改下載檔名的擴充功能，以及企業政策。

## 其他瀏覽器 {#other-browsers}

格式正確的標頭，以及最常見的幾種不合格寫法，Firefox 和 Safari 的結果跟 Chrome 一致：不論順序都以 `filename*` 優先、語言標記會被忽略、`filename` 裡的原始 UTF-8 照 UTF-8 解碼、引號內的分號是檔名的一部分、結尾多一個 `;` 也沒關係，沒寫處置類型的標頭也照讀。其餘的就各有不同：

| 行為 | Chrome | Firefox | Safari |
| --- | --- | --- | --- |
| `filename` 裡的百分比編碼會被解碼 | 是 | 是 | 否 |
| RFC 2047 的 encoded word 會被解碼 | 是 | 是 | 否 |
| RFC 2231 分段（`filename*0=`）會被接起來 | 否 | 是 | 否 |
| Windows 不允許的字元（例如 `<`、`?`、`*`）會被替換 | 是 | 是 | 否 |
| 結尾的空白會變成 | `_` | 被去掉 | 保留空白 |

[Browsers workflow](https://github.com/birdhackor/browser-download-filename/actions/workflows/browsers.yml) 會用 Firefox，以及 Linux 和 macOS 上的 WebKit 下載每一個測試案例，每次執行的摘要都會列出它們跟 Chrome 檔名不同的案例。上表就是這些執行的結果，使用 Playwright 1.64：Firefox 157，以及代表 Safari 的 macOS 上的 WebKit 27.2；macOS 上的 WebKit 跟 Safari 一樣，透過 Apple 的網路程式碼決定下載檔名。831 個案例中，Firefox 有 423 個、macOS 上的 WebKit 有 309 個跟 Chrome 的檔名相同。

## 移植的限制 {#limits-of-the-port}

- **值裡的標頭行。** 本套件分開讀每一個標頭值（見[讀取標頭行](#reading-header-lines)）。值裡的換行後面接著另一行標頭時，這個值在換行處結束，但本套件不會像 Chrome 那樣把那一行讀成標頭：在 `attachment; filename=a.pdf\rContent-Disposition: attachment; filename=b.pdf` 裡，它看不到第二個 Content-Disposition，而 Chrome 會因此拒絕這個回應。值裡的空行，或值結尾的 LF（它跟後面的換行構成空行），會在線上結束標頭；本套件在那裡結束這個值，但仍會繼續讀之後的標頭行。[使用方式](usage.md#pass-the-headers-from-your-http-library)介紹的 HTTP 函式庫會把這種行切成各自獨立的標頭行、在空行處結束標頭，或拒絕這個回應，所以只有自己組出標頭行時才需要注意。
- **其他拒收的原因。** Chrome 拒絕回應的原因不只 `blocks_download` 回報的那兩種，例如重複出現、值又不同的 Location 標頭。本套件不檢查這些原因，`suggested_filename` 也照樣給出檔名。
- **MIME sniffing。** Chrome 檢查內容來決定 MIME 類型時，本套件用宣告的類型，所以副檔名可能跟 Chrome 的不同。只模擬 Chrome 經由網路載入的下載：Playwright 的 `route.fulfill`，以及 `blob:`、`data:`、`file:` 網址，可能得到不同的 MIME 類型。
- **主機名稱。** Chromium 用 UTS #46 轉換非 ASCII 的主機名稱，本套件用的是 Python 的 IDNA 2003 codec。兩者對某些主機名稱是否合法（以數字結尾的由右至左標籤、超過 63 個字元的標籤）以及主機名稱的 ASCII 形式（`ß` 和 `ς`）看法不同。這只影響主機名稱含非 ASCII 字元的網址。requests、httpx、httpx2 和 aiohttp 在 `response.url` 裡給的都是 ASCII 形式的主機名稱，`urllib.request` 則照請求時的網址原樣給出。
- **網址是否合法。** 主機名稱不會被當成 IPv4 位址解析，所以 Chromium 因為位址格式錯誤而拒絕的網址，在這裡仍可能得到檔名。瀏覽器能載入的網址，兩邊得到的檔名都相同。
- **Unicode 版本。** `filename*` 的 NFC 正規化用的是執行中 Python 的 Unicode 版本；Chromium 的 ICU 是 Unicode 17.0，Python 3.15 也是。兩者只會在舊版本沒有的字元上不同。
