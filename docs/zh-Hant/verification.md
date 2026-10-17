# 如何驗證

本套件宣稱替檔案命名的方式跟 Chromium 相同。下列測試支撐這個說法，CI 在每次變更時都會執行，涵蓋 CPython 3.11 到 3.15 和 PyPy 3.11，以及 Linux、macOS 和 Windows。

## Chromium 自己的測試案例 {#chromiums-own-test-cases}

本套件移植的 Chromium 程式碼都附有單元測試：`net/http/http_content_disposition_unittest.cc`、`net/http/http_util_unittest.cc`、`net/base/filename_util_unittest.cc` 和 `base/i18n/file_util_icu_unittest.cc`。這些案例逐一移植成 `tests/test_chromium_*.py` 裡 600 多個測試，包括針對 Windows 的預期結果。

## 字元集解碼器 {#the-charset-decoders}

Chromium 用自己那份 ICU 解碼舊式字元集，結果跟 Python 的 codec 不完全一樣。單位元組字元集的對照表，是從那份 ICU 資料產生的。多位元組字元集（Shift_JIS、EUC-JP、ISO-2022-JP、GBK、gb18030、Big5 和 EUC-KR）則使用 Python 的 codec，在 Chromium 的 ICU 對照不同的地方加以修正，並照 ICU 的方式切分不合法的輸入。有一個測試會把 ICU 的狀態表對每個字元集接受的所有位元組序列都解碼一次，再把結果的摘要值跟從 ICU 對照檔產生的摘要值比較；所以只要某個 Python 的 codec 跟 Chromium 不一致，這個測試就會失敗。

## 真正的 Chromium {#a-real-chromium}

`tests/browser/` 裡的瀏覽器測試，從本機的 HTTP 伺服器逐位元組送出每個案例的回應標頭，透過 Playwright 用 Chromium 下載，再把 Chromium 回報的建議檔名，跟 `suggested_filename` 對同樣的網址和標頭算出的結果比較。案例共有 936 個：

- Chromium 單元測試裡的標頭；
- 實務上看得到的標頭：兩種參數順序、語言標記、原始 UTF-8、百分比編碼、RFC 2047、引號和分號、結尾的分號、重複的標頭；
- 含有折行、其他換行、空行和 NUL 的標頭值，以及名稱和冒號之間有空白和 tab 的標頭；
- 網址、Content-Type 和 X-Content-Type-Options 標頭，以及 `<a download>` 的值；
- Chromium 認得的每一個字元集標籤；
- 每個單位元組字元集的每一個字元、每個多位元組字元集裡三個位元組以內的每一個字元、gb18030 四位元組字元的取樣，以及 Python codec 和 ICU 看法不同的位元組序列；
- 150 個從觸及解析器邊界情況的片段隨機拼成的標頭。

案例分成兩組，在 `tests/browser/corpus.py` 裡逐案列出。精確集合（`exact_cases()`，920 個案例）的檔名由標頭和網址決定：每一個案例，Chromium 都必須給出 `tests/browser/test_browsers.py` 的 `chromium_expectation` 依本套件的規則預測的結果，否則 CI 失敗：通常是本套件的檔名；本套件判定 Chrome 會拒收時，則是不下載，或只由 `download` 屬性和網址決定的檔名。限制集合（16 個案例）是 Chromium 會檢查內容來決定 MIME 類型的回應，本套件在這裡改用宣告的類型（見 [MIME 類型](behavior.md#the-mime-type)）：每一個案例，Chromium 都必須開始下載，並給出針對其內容列出的檔名，本套件也必須給出針對其標頭和網址列出的檔名。同一批案例也會用 Firefox，以及 Linux 和 macOS 上的 WebKit 執行；這些執行不會因為結果不同而失敗，而是在摘要裡列出跟 Chrome 檔名不同的案例（見[行為與瀏覽器差異](behavior.md#other-browsers)）。

自己執行瀏覽器測試：

```console
uv sync
uv run playwright install chromium
uv run pytest tests/browser --with-browser chromium --browser-report report.json
```

`--with-browser` 接受 `chromium`、`firefox` 或 `webkit`，可以重複指定；`--browser-report` 還會在 JSON 檔旁邊寫一份 Markdown 摘要。

## HTTP 函式庫 {#the-http-libraries}

[使用方式](usage.md#pass-the-headers-from-your-http-library)示範了怎麼從 httpx2、httpx、requests、aiohttp 和 `urllib.request` 傳入標頭。`tests/http_clients/` 裡的測試從本機的 HTTP 伺服器逐位元組送出標頭行，包括重複的 Content-Disposition 行、沒關上的引號、舊式字元集和 UTF-8 的位元組、多行 Content-Type、X-Content-Type-Options、折行和其他換行、NUL，以及比某些函式庫上限更長、更多的標頭行。測試用各個函式庫取回它們，再照使用方式的寫法交給本套件，結果必須跟原樣傳入送出的標頭行時相同。使用方式說某個函式庫讀這些行的方式跟 Chrome 不同或會拒收，或另一種傳法會得到不同檔名的地方，測試也檢查那個檔名，或函式庫丟出的例外。文件對這些函式庫本身的說法同樣有測試檢查，aiohttp 的兩種 HTTP parser 也都會跑。CI 在 CPython 3.11 和 3.15 上執行這些測試，每週的 canary 則用最新版的函式庫執行：

```console
uv sync
uv run pytest tests/http_clients --with-http-clients
```

## 性質測試 {#properties}

用 Hypothesis 產生輸入，檢查：

- 解析任何位元組或字串都不會丟出例外；
- 含有換行和 NUL 的標頭值，讀出的結果跟逐行模擬 Chromium parser、在完整回應標頭裡讀出的結果相同；
- `suggested_filename` 一定回傳非空的檔名，不含任何位置都不允許的字元，開頭和結尾也沒有不允許出現在那裡的字元；
- 同一個檔名再清洗一次不會改變；例外有兩個，都跟 Chromium 一樣：只由 `-` 和 `_` 組成的檔名會變成 `download`；`platform="windows"` 時，`~` 可能到第二次才變成 `_`，因為「檔名可能是 8.3 短檔名、所以要換掉 `~`」是在替換其他不允許的字元之前判斷的（`0~|` 先變成 `0~_`，再變成 `0__`）；
- 檔名經過 `filename*` 編碼再解碼後保持不變；
- 刻意構造的大型輸入，處理時間跟輸入長度成線性關係。

## 跟進 Chromium {#following-chromium}

本套件跟隨一個釘選的 Chromium 版本（`browser_download_filename._data` 裡的 `CHROMIUM_REVISION`），以及該版本 Chromium 釘選的 ICU 版本。每週一次的 canary 會：

- 用 Playwright 提供的最新 Chromium 執行瀏覽器測試，所以 Chromium 的行為一旦改變，就會出現失敗的案例；
- 檢查移植來源的 Chromium 檔案或 ICU 版本，在釘選版本之後有沒有變動；
- 在最新的 Python 上安裝已發布的套件，並用最新版的測試工具執行測試。
