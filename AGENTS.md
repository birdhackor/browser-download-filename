# AGENTS.md

## 這是什麼

`browser-download-filename` 把 Chromium 的 Content-Disposition 解析器與下載檔名規則（`net::GetSuggestedFilename`）移植成純 Python、沒有執行期相依的套件。**對錯的標準是「跟 Chromium 給出同一個名字」**，不是 RFC：兩者不同時一律照 Chromium。

`MAINTENANCE.md`（正體中文）是維護 runbook。以下流程照它的章節做，不要另起一套：〈跟進 Chromium〉（升級釘選的 Chromium／ICU revision）、〈升級 Playwright〉、〈HTTP 函式庫測試〉（HTTP 函式庫改了行為）、〈Python 支援窗〉、〈發布〉、〈發布後與補救〉。

## 常用指令

`uv sync` 會裝預設的 `dev` group（test、lint、Playwright 套件本身，以及使用說明示範或描述的 HTTP 函式庫：`http-clients` group）。

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run mypy          # strict；範圍是 src、tests、scripts、.github/scripts
uv run pytest        # 沒有 --with-browser、--with-http-clients 時，tests/browser、tests/http_clients 一律 deselect

uv run pytest tests/test_url.py::test_parse_url_parts            # 單一測試
uv run pytest tests/test_behavior.py -k precedence
uv run pytest "tests/test_docs.py::test_examples[README.md]"     # 單一文件的範例；id 是相對路徑，如 docs/en/usage.md
```

`__version__` 讀的是已安裝套件的 metadata：沒有安裝、只把 `src` 加進 `PYTHONPATH` 時，import 會丟 `PackageNotFoundError`。一律透過 `uv run` 執行。

瀏覽器比對測試要先裝 Playwright 釘的瀏覽器：

```sh
uv run playwright install chromium     # 全新的 Linux 加 --with-deps
uv run pytest tests/browser --with-browser chromium --browser-report browser-report-chromium.json
```

`--with-browser` 可重複指定 `chromium`、`firefox`、`webkit`；`--browser-report` 會在旁邊另寫一份 Markdown 摘要，只列結果不同的案例。

HTTP 函式庫測試要 `http-clients` group 的函式庫（`uv sync` 已裝）；給了旗標卻缺函式庫時，pytest 直接報錯而不是 skip：

```sh
uv run pytest tests/http_clients --with-http-clients
```

檢查 `_data.py` 是否仍是 generator 的產物。需要網路，也需要 `unicodedata.unidata_version` 等於 `UNICODE_VERSION` 的 Python；拿掉 `--check` 就是重新產生：

```sh
uv run --no-project --python 3.15 scripts/generate_data.py --check
```

文件預覽（zensical 版本跟 `.github/workflows/docs.yml` 一致；中文站換成 `zensical.zh-Hant.toml`）：

```sh
uvx --python 3.15 zensical==0.0.70 serve --config-file zensical.en.toml
```

`docs.yml` 用 `--strict` 建置：連到不存在的頁面或 anchor 會讓建置失敗。改了文件就在本機用同樣的方式建置兩個語言（輸出在 `site/`，已列入 `.gitignore`）：

```sh
uvx --python 3.15 zensical==0.0.70 build --config-file zensical.en.toml --clean --strict
uvx --python 3.15 zensical==0.0.70 build --config-file zensical.zh-Hant.toml --clean --strict
```

## 架構

公開 API 只有 `__init__.py` 匯出的 `parse_content_disposition`、`suggested_filename`、`sanitize_filename`、`ContentDisposition`、`HeadersLike` 與 `__version__`，其餘都是私有模組。移植的函式沿用 Chromium 的名字（轉成 snake_case），或在 docstring 寫出對應的 Chromium 函式（如 `HttpUtil::TrimLWS`、`GetSuggestedFilenameImpl`）；要對照上游，就搜尋那個名字。

處理順序：

1. **從標頭容器取值**（`_headers.header_lines`）：`headers`（以及 `parse_content_disposition` 收到的 `value`，除非它是 `None`、str 或 bytes 類）是有 `.items()` 的物件或 `(名稱, 值)` 配對的 iterable（型別是 `HeadersLike`）。只走訪一次，依序收成 `(名稱, 值)` 清單（`HeaderLines.lines`），值是 list／tuple 時每個元素算一行；之後要查哪個標頭都用 `header_values` 從這份清單查。不要先轉成 dict：那會丟掉重複的行與順序。每個配對的名稱代表該行冒號之前的部分，照 HTTP/1 路徑的 `HttpUtil::HeadersIterator::GetNext` 比對（`_headers._lookup_name`；瀏覽器測試只驗證 HTTP/1.1）：名稱是空的或以 SP、HT 開頭，或去掉結尾的 SP、HT（`TrimLWS`）之後不是 token 時，`GetNext` 略過這一行，清單裡也沒有它，但它的值照樣讀、NUL 照樣算；其他名稱去掉結尾的 SP、HT 後轉成 ASCII 小寫，查找時不分 ASCII 大小寫（`HttpResponseHeaders::FindHeader`）。`TrimLWS` 只去 SP、HT，所以不能用不帶參數的 `strip`／`rstrip`（會連 VT、FF、CR、LF 一起去掉）。名稱含冒號、CR、LF，或以 SP、HT 開頭時，Chrome 在線上讀到的行跟本套件不同（第一個冒號結束名稱、CR 與 LF 換行、以 SP 或 HT 開頭的行可能接到前一行）；本套件不把各行重組成整段標頭，這寫在文件的限制裡。走訪時就檢查每一個標頭的形狀與型別、還原位元組並照線上的方式讀值（〈還原位元組〉與〈照線上的方式讀值〉兩步），所以這些呼叫端錯誤都在解析任何標頭之前丟出。`suggested_filename` 的 `content_disposition=` 不是 `None` 時（空字串也算），取代清單裡所有的 Content-Disposition 行。
2. **還原位元組**（`_bytes.header_bytes`）：Chromium 解析的是線上的原始位元組，所以所有解析都在 `bytes` 上做。bytes 原樣使用。HTTP 函式庫給的 `str` 先還原：有 `headers_encoding` 時一律 `value.encode(headers_encoding, "surrogateescape")`，編不回去丟 `ValueError`；沒有時用推測規則：每個字元都在 U+0000–U+00FF、而且這些 Latin-1 位元組是合法 UTF-8 時，直接用它們（requests、urllib3、`http.client` 的情形）；否則當成文字以 UTF-8 編碼，surrogate escape（aiohttp）還原成原本的位元組。
3. **照線上的方式讀值**（`_headers.line_value`，用 `_http` 的 `locate_end_of_headers` 與 `assemble_raw_headers`）：每個值都當成該行標頭冒號之後、照送出原樣的其餘部分來讀，包括 `headers` 的每一行（list 值的每個元素）、`content_disposition=`、`content_type=` 與 `parse_content_disposition` 的單一值。Chromium 的 HTTP/1 路徑在解析任何標頭前做三件事，這裡逐值照做：值在第一個空行（`\n\r?\n`，`HttpUtil::LocateEndOfHeaders`）截斷；截斷後的值或任何一行的名稱（照給的原樣、修剪之前，`GetNext` 略過的行也算）含 NUL，就代表 Chrome 拒收（`HttpResponseHeaders::TryToCreate` 的 `HasEmbeddedNulls`，`ERR_INVALID_HTTP_RESPONSE`），記在 `has_nul`，NUL 不刪；再依 CR、LF 的連續段切行（`HttpUtil::AssembleRawHeaders`）：以 SP 或 HT 開頭的行換成一個空白接上（去掉該行開頭的 LWS、保留前一行結尾的 LWS），遇到其他行，值就到此為止。只有 CR、LF 是換行，VT、FF 不是，所以不能用 `splitlines`。值裡換行之後的另一行標頭不讀成新標頭，空行之後的其他標頭行照樣讀：這兩點寫在文件的限制裡。
4. **切標頭**（`_http`，HttpUtil 的迭代器）：每一行 Content-Disposition 依引號外的逗號切開（去掉前後 LWS、保留空值），接成一份值清單，命名只用第一個值（`HttpResponseHeaders::EnumerateHeader`）。清單裡只要有一個值跟第一個值逐位元組不同，`ContentDisposition.blocks_download` 就是 `True`：Chromium 以 `ERR_RESPONSE_HEADERS_MULTIPLE_CONTENT_DISPOSITION` 拒絕整個回應（`HttpUtil::HeadersContainMultipleCopiesOfField`）；單一行的 `attachment,` 或 `filename=a,b.txt` 也會。上一步發現 NUL 時，`blocks_download` 也是 `True`。Chrome 還有其他拒收的原因（例如 Location 重複出現且值不同），`blocks_download` 不涵蓋，`behavior.md` 的〈Limits of the port〉列為限制。`suggested_filename` 不回報拒收，照樣用第一個值命名。參數由左到右讀，遇到第一個格式錯誤的參數就結束。
5. **解析 Content-Disposition**（`_content_disposition._parse`）：`filename*`（RFC 8187）解得開就優先，否則用 `filename`。後者照瀏覽器而不是 RFC 解碼，規則見 `docs/en/behavior.md` 的〈Reading Content-Disposition〉。`parse_content_disposition` 給的檔名**沒有清洗**，可能含路徑分隔符號。
6. **推導 MIME type**（`_mime.download_mime_type`）：只在有 `headers` 或 `content_type` 時推導，兩者都沒有就不用 MIME。Content-Type 行是 `content_type=`（不是 `None` 就是唯一的一行，空字串也算）或清單裡所有的 Content-Type 行；X-Content-Type-Options 只來自 `headers`。網路層（`HttpResponseHeaders::GetMimeTypeAndCharset`）：各行去掉前後 LWS、以 `, ` 接起來，在引號外的逗號處切開、略過空值，每個值依序交給 `HttpUtil::ParseContentType`：`net::ParseMimeType` 取得的 type 從第一個非 LWS 字元到 ` \t;(` 之前、必須包含第一個 `/`，不做 token 檢查；取不到 type 或整個值剛好是 `*/*` 時不改變結果，否則換成 ASCII 小寫的 type。接著照 `net::ShouldSniffMimeType` 判斷 Chrome 會不會 sniff 內容（scheme、X-Content-Type-Options 第一行的第一個值、手寫的可 sniff 型別清單與 unknown 型別）：不會時，空型別與 feed 型別換成 `text/plain`（`services/network/url_loader.cc`）；會時沿用宣告的型別，因為本套件沒有內容可讀。
7. **產生檔名**（`_filename.suggested_filename` → `_get_suggested_filename` → `_generate`）：依序取 Content-Disposition、`download_attribute`（`<a download>` 的值）、URL 路徑最後一段（`_url` 只重現 GURL 中會影響檔名的部分）、host（僅在 `default_name` 為 `None` 時）；接著清洗、替換非法字元、依 MIME 補上或修正副檔名（名字來自 Content-Disposition 時不動副檔名）。`_get_suggested_filename` 收的是 `net::GetSuggestedFilename` 的引數，`mime_type` 原樣查表，跟 Chromium 一樣不轉小寫、不去參數。`sanitize_filename` 走同一條路徑，等於只給 `download_attribute` 的 `suggested_filename`。
8. **字元集**（`_charset`）：模擬 Chromium 內建的 ICU。名稱以 `strip_for_compare` 鬆散比對 `CHARSET_ALIASES`，用的是 WHATWG 標籤，所以 `ISO-8859-1` 是 windows-1252。單位元組字元集查產生的表；多位元組字元集用 Python codec，其中有 ICU 狀態表的（`MULTI_BYTE_STATES`）另依狀態表切字元，並套用產生的修正。

對照 Chromium 時要知道的：

- 公開參數 `fallback_charset`、`download_attribute` 在內部沿用 Chromium 的名字 `referrer_charset`、`suggested_name`；`default_name=None` 在內部是 Chromium 的空字串 default name。`content_type` 是一行 Content-Type 標頭；內部的 `mime_type` 則是 `_mime` 推導出、交給 `net::GetSuggestedFilename` 的型別。
- 被拒的回應（`blocks_download`：Content-Disposition 的值彼此不同，或標頭裡有 NUL）：一般連結什麼都不下載（Chrome 顯示錯誤頁面）；有 `download` 屬性的連結仍會開始一個失敗的下載，名字是在沒有 Content-Disposition、也沒有 MIME type 的情況下算出來的（`download_response_handler.cc` 的失敗路徑），也就是只看 `download` 屬性與網址。`tests/browser/test_browsers.py` 的 `chromium_expectation` 照這個規則預期。
- `platform="windows"` 對應 Chromium 的 `#if BUILDFLAG(IS_WIN)` 分支（內部是 `windows: bool`）。預設的 `None` 在呼叫時依 `sys.platform` 決定：Windows 上用 Windows 規則，其他用 POSIX 規則；所以結果會因平台而不同的測試與文件範例要明確傳 `platform=`，不能依賴執行它的作業系統。其他依作業系統而異的部分（非 UTF-8 的原始位元組、MIME 資料庫）以 Linux 上的 Chrome 為準；CI 的 Chromium 比對也在 Linux 跑。

有測試守著的不變式（`test_properties.py`、`test_input.py`、`test_headers.py`）：

- 格式錯誤的標頭**永不 raise**，回傳 Chromium 對它的解讀。只有呼叫端的錯誤會丟例外：型別不對，包括 `headers` 的形狀（`TypeError`）、Chromium 開不了的 `fallback_charset` 或 Python 不認得、不是文字 codec 的 `headers_encoding`（`LookupError`）、未知的 `platform`、空字串的 `default_name`，或用 `headers_encoding` 編不回去的 str 標頭值（`ValueError`）。這些都在解析任何標頭之前丟出。
- `suggested_filename` 與 `sanitize_filename` 永遠回傳非空、可以當檔名的字串。
- 惡意構造的大輸入必須很快處理完（`test_large_adversarial_inputs_are_fast` 會計時）。改 `_http` 的 regex 或解碼迴圈時，注意回溯與二次方的行為。

### 產生的資料

`src/browser_download_filename/_data.py` 由 `scripts/generate_data.py` 從釘選的 Chromium 與 ICU revision 產生，內容是 charset 別名、單位元組表、多位元組的狀態表、修正與摘要、MIME 對照、Unicode Cf 範圍。**不手改**，ruff 也排除它。釘選值的來源是 generator 裡的常數（`CHROMIUM_REVISION`、`CHROMIUM_COMMIT_POSITION`、`ICU_REVISION`、`UNICODE_VERSION`），`_data.py` 只是抄一份。

## 測試

- `test_chromium_*.py`：逐案移植的 Chromium 單元測試。`tests/browser/corpus.py` 直接 import `test_chromium_content_disposition.py` 的案例清單，改名或改形狀會牽動瀏覽器語料。上游的 `HttpContentDispositionTest` 把每個案例組成一份回應標頭、經 `AssembleRawHeaders` 再解析，所以這些案例走公開的 `parse_content_disposition`；只有 `test_contains_nul` 走 `_parse`（上游直接用字串建構子）。`test_chromium_http_util.py` 把 `AssembleRawHeaders` 的案例改成逐值的形式。`test_chromium_filename_util.py` 經 `_get_suggested_filename` 直接給 Chromium 核心收到的 `mime_type`，不經 `_mime` 的推導。
- `test_mime.py`：`_mime` 的網路層解析、X-Content-Type-Options 與可 sniff 型別的判斷、URLLoader 的轉換，以及公開入口如何從 `headers` 與 `content_type` 取得 MIME type。
- `test_api.py` 鎖住公開名稱、參數順序與參數種類（positional-only、keyword-only）。改 API 時一起改它與兩種語言的 `api-reference.md`。
- `test_headers.py`：`HeadersLike` 的各種形狀、順序、只走訪一次、`content_disposition=` 的取代、`blocks_download` 的規則，以及值裡的換行、空行與 NUL 照線上的方式讀。`SHAPES` 標成 `HeadersLike`，讓 mypy 檢查這些形狀在型別上也被接受。
- `test_docs.py` 執行 README 與 `docs/*/*.md` 裡每個 ```` ```pycon ```` 區塊，同一份文件的區塊共用命名空間；行為一改，範例的輸出也要跟著改。需要網路、不該執行的範例用 ```` ```python ````。它也禁止 README、`docs`、`MAINTENANCE.md`、`src`、`tests`、`scripts` 出現看不見或會重排文字的字元（例如 U+202E、全形空白）：程式碼裡寫成 escape，文件裡寫成 U+XXXX。
- `test_charset.py` 把 ICU 狀態表接受的每個序列的解碼摘要跟 `MULTI_BYTE_DIGESTS` 比較，所以某個 Python 版本的 CJK codec 一改就會失敗。修法是讓 generator 把差異也寫成修正，不是放寬測試。
- `tests/browser/`：本機伺服器依序逐位元組送出每個案例的標頭行與內容，經 Playwright 點連結下載，比對 `download.suggested_filename`。案例分兩組，在 `corpus.py` 逐案列出：**精確集合**（`exact_cases()`，標頭與網址就決定檔名）Chromium 必須跟本套件全部一致；**限制集合**（`limited_cases()`，`LimitedCase`：Chrome 會 sniff 內容）由另一個測試斷言下載有發生、Chromium 給出針對該內容列出的名字、本套件給出列出的退路名字。案例屬於哪一組由人列出，不能用本套件的 sniff 判斷式決定。Firefox 與 WebKit 跟 Chrome 不一致只記 xfail。Chromium 不一致時，先判斷是移植的 bug 還是 Chromium 改了行為，不要改預期值去遷就測試。新增語料案例時，id 必須唯一（`all_cases()` 會檢查）。伺服器原樣送出標頭值，值裡的 CR、LF、NUL 就是線上的位元組（`test_the_server_sends_the_header_lines_of_each_case_byte_for_byte` 會檢查）：值裡換行之後若接另一行標頭，Chromium 讀得到、本套件讀不到，所以精確集合的案例不能讓這一行改變結果；空行也一樣，它之後的標頭行不能改變結果。名稱含冒號、CR、LF 或以 SP、HT 開頭的案例也一樣，Chromium 從線上另外讀到的行不能改變結果。從 Chromium 單元測試自動匯入的案例由 `_unit_test_header_fits_one_line` 排除含 CR、LF、NUL 的值；這類案例逐案列在 `RAW_LINE_CASES`。
- `tests/http_clients/`：本機伺服器逐位元組送出每個案例的標頭行，httpx2、httpx、requests、aiohttp、`urllib.request` 照 `docs/*/usage.md` 的寫法取回並呼叫本套件，結果必須等於把送出的標頭行原樣傳入的結果；使用說明說「會不同」的傳法，以及函式庫自己接折行、丟掉標頭行或拒收回應的地方（`LIBRARY_DIFFERENCES`），把不同的結果或丟出的例外寫成預期值。文件對這些函式庫的其他說法（例如解碼用的 codec、依名稱取標頭的結果、重新導向、`response.url` 的主機名稱）也在這裡檢查。aiohttp 的 C 與 Python 兩種 parser 都跑，C parser 不存在就失敗。改了使用說明、README 或 api-reference 裡的函式庫範例或說法，就一起改它。
- pytest 開了 `--strict-markers`、`--strict-config` 與 `xfail_strict = true`。

## CI 會擋、本機不一定看得到的事

- CI 測的是**建好的 wheel**，不是 `src/`，矩陣（`ci.yml` 的 `test`）也含 PyPy；另外把 sdist 解開、重建、再測一次。`http-clients` job 也裝建好的 wheel，在 `requires-python` 的下限與最新的 CPython 上帶 `--with-http-clients` 跑 `tests/http_clients`。程式碼必須相容 `requires-python` 的下限，ruff 的 `target-version` 與 mypy 的 `python_version` 也設在那裡。
- `.github/scripts/check-dist.py` 寫死了 wheel 裡應有的套件檔案（`MODULES`，必須完全相同）、sdist 的必備檔案、`Requires-Python` 與 License-Expression，而且不准有任何執行期相依。增刪或搬動這些檔案、改到這些 metadata 時，一起改它。
- 改了 `pyproject.toml` 的版本、相依或 `requires-python` 就執行 `uv lock`；CI 安裝環境時一律 `--locked`，lock 沒同步就直接失敗。
- `README.md` 也是 PyPI 的套件頁，PyPI 會弄壞相對連結，所以裡面的連結一律寫絕對網址。

## 文件

- `docs/en` 與 `docs/zh-Hant` 的頁面一一對應，改一邊就要改另一邊，`changelog.md` 也是。中文標題用 `{#...}` 指定跟英文相同的 anchor。
- 文件裡寫死了量測值：瀏覽器案例數、Firefox／WebKit 跟 Chrome 一致的案例數與量測時的瀏覽器版本，以及概數（`README.md` 與 `index.md` 的瀏覽器案例數、`verification.md` 的移植測試數）。改了語料、移植了新的 Chromium 測試或升級 Playwright 之後，依新的數字與報告更新兩種語言的 `verification.md`、`behavior.md`、`index.md` 與 `README.md`。
- 程式碼、註解、docstring 與 README 用英文；`MAINTENANCE.md` 用正體中文。
