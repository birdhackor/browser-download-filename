# 行為與瀏覽器差異

這一頁說明本套件遵循的規則（也就是 Chromium 的規則）、Chrome 在這之外還做了什麼，以及 Firefox 和 Safari 的命名哪裡不同。

## 讀取 Content-Disposition {#reading-content-disposition}

- **只看第一個值。** 標頭會在引號外的逗號處切開，只讀第一段；所以 HTTP 函式庫用 `, ` 接起來的多個標頭，等於只看第一個。切出來的幾段彼此不同時，Chrome 會拒絕整個回應，什麼都不下載。內容不同的重複標頭會這樣，只有一個標頭、但引號外有逗號時也會，例如 `filename=a,b.txt` 或結尾多一個逗號。本套件無法回報這種情況，它會用第一段決定檔名。
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
4. 套用 `content_type` 的副檔名規則和 Windows 規則，說明見[使用方式](usage.md#add-an-extension-from-the-content-type)。

所以由 `report`、U+202E 和 `txt.exe` 組成、看起來像 `reportexe.txt` 的檔名，會變成 `report_txt.exe`。

## Chrome 在這之外還做的事 {#what-chrome-does-beyond-this}

本套件回傳的是下載開始時，Chrome 回報給 DevTools 和 Playwright 的檔名。Chrome 最後實際寫入的檔案，名稱可能不同：

- **預設文字編碼。** 遇到不是 UTF-8 的原始位元組，Chrome 會用瀏覽器的預設文字編碼解碼。請把它傳給 `fallback_charset`（見[使用方式](usage.md#decode-legacy-charsets)）。
- **MIME sniffing。** 沒有 `X-Content-Type-Options: nosniff` 時，Chrome 可能檢查內容後改用跟 Content-Type 標頭不同的 MIME 類型，並依它決定副檔名。
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

[Browsers workflow](https://github.com/birdhackor/browser-download-filename/actions/workflows/browsers.yml) 會用 Firefox，以及 Linux 和 macOS 上的 WebKit 下載每一個測試案例，每次執行的摘要都會列出它們跟本套件結果不同的案例。上表就是這些執行的結果，使用 Playwright 1.64：Firefox 157，以及代表 Safari 的 macOS 上的 WebKit 27.2；macOS 上的 WebKit 跟 Safari 一樣，透過 Apple 的網路程式碼決定下載檔名。831 個案例中，Firefox 有 423 個、macOS 上的 WebKit 有 309 個跟 Chrome 的檔名相同。

## 移植的限制 {#limits-of-the-port}

- **主機名稱。** Chromium 用 UTS #46 轉換非 ASCII 的主機名稱，本套件用的是 Python 的 IDNA 2003 codec。兩者對某些主機名稱是否合法（以數字結尾的由右至左標籤、超過 63 個字元的標籤）以及主機名稱的 ASCII 形式（`ß` 和 `ς`）看法不同。這只影響主機名稱含非 ASCII 字元的網址，而 HTTP 函式庫不會把這種網址放進 `response.url`：requests、httpx 和 aiohttp 給的都是 ASCII 形式的主機名稱。
- **網址是否合法。** 主機名稱不會被當成 IPv4 位址解析，所以 Chromium 因為位址格式錯誤而拒絕的網址，在這裡仍可能得到檔名。瀏覽器能載入的網址，兩邊得到的檔名都相同。
- **Unicode 版本。** `filename*` 的 NFC 正規化用的是執行中 Python 的 Unicode 版本；Chromium 的 ICU 是 Unicode 17.0，Python 3.15 也是。兩者只會在舊版本沒有的字元上不同。
