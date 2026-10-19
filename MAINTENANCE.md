# 維護與發布 Runbook

## 開發環境

工具鏈以 uv 管理，CI 釘在 uv 0.13.1（`setup-uv` 的 `version`），build backend 是同一條線的
`uv_build`（`pyproject.toml` 的 `[build-system]`）。`uv sync` 會裝好預設的 `dev` group
（`test`、`lint`、`browser` 與 `http-clients`）。`browser` 只有 Playwright 套件本身，
`http-clients` 是使用說明示範或描述的 HTTP 函式庫；兩者放進 `dev`，是為了讓 mypy 用它們的型別
檢查瀏覽器測試與 HTTP 函式庫測試。瀏覽器要另外用 `playwright install` 安裝：

```sh
uv sync
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

`tests/` 底下分成幾層：`test_chromium_*.py` 是逐案移植的 Chromium 單元測試；
`test_charset.py`、`test_url.py`、`test_mime.py`、`test_behavior.py`、`test_input.py` 補上
移植測試沒涵蓋的細節；`test_properties.py` 是 Hypothesis 性質測試；`test_docs.py` 執行 README 與
`docs/*/*.md` 裡的 ```` ```pycon ```` 範例，並禁止 README、文件與原始碼出現 U+202E 這類
看不見或會重排文字的字元（程式碼裡寫成 escape，文件裡寫成 U+XXXX）；
`test_api.py` 鎖住公開 API 的名稱與簽章。`tests/browser/` 是瀏覽器比對測試，沒有
`--with-browser` 時一律 deselect；`tests/http_clients/` 檢查文件對 HTTP 函式庫的寫法與說法，
沒有 `--with-http-clients` 時一律 deselect（見〈HTTP 函式庫測試〉）。

文件裡的 ```` ```pycon ```` 區塊都會被測試執行，改 API 或行為時，範例的輸出也要跟著改。
不想被執行的程式碼（需要網路的 HTTP 函式庫範例，例如 httpx2、requests、aiohttp）用
```` ```python ````；這些範例的寫法由 `tests/http_clients/` 檢查（見〈HTTP 函式庫測試〉）。

## Python 支援窗

`requires-python = ">=3.11"`。CI matrix（`.github/workflows/ci.yml` 的 `test`）跑
CPython 3.11–3.15、PyPy 3.11 的 Ubuntu，加上 3.15 的 macOS 與 Windows；測的是建好的
wheel，不是 `src/`。純 Python 套件沒有 ABI 問題，所以只有一顆 `py3-none-any` wheel。
同一個 workflow 的 `http-clients` job 只跑支援範圍的兩端，也就是 Ubuntu 上的 CPython 3.11 與
3.15，同樣裝建好的 wheel（見〈HTTP 函式庫測試〉）。

- 新的 CPython 進入 beta 後，weekly canary 就會用它跑已發布的套件（見下文）；到 RC 或正式版時
  把它加進 CI matrix 與 `pyproject.toml` 的 classifiers，`http-clients` job 的最新版也換成它
  （aiohttp 要先有這個版本的 wheel，見〈HTTP 函式庫測試〉），並更新 README、
  `docs/*/index.md`、`docs/*/verification.md` 與這份文件。
- 某個版本 EOL 後，在下一個 minor 版移除：調高 `requires-python` 並執行 `uv lock`（lock 也記著
  它，沒同步 `--locked` 就會失敗）、改 matrix（`test`，以及 `http-clients` 的下限）、
  classifiers、`tool.ruff` 的 `target-version`、`tool.mypy` 的 `python_version`、
  `.github/scripts/check-dist.py` 檢查的 `Requires-Python` 與文件。
- `lint` job 用最新的 CPython（目前 3.15）。`scripts/generate_data.py` 則必須用 `unicodedata`
  版本等於 `UNICODE_VERSION` 的 CPython，見〈跟進 Chromium〉。

## 瀏覽器比對測試

`browser` dependency group 釘死 Playwright（`playwright==1.64.0`），而 Playwright 的版本決定
測試用的 Chromium、Firefox 和 WebKit 版本。本機執行：

```sh
uv sync
uv run playwright install chromium        # 全新的 Linux 加上 --with-deps
uv run pytest tests/browser --with-browser chromium --browser-report browser-report-chromium.json
```

`--with-browser` 可以重複指定 `chromium`、`firefox`、`webkit`；`--browser-report` 另外在
旁邊寫一份 Markdown 摘要（依精確集合與限制集合分開計數，只列跟 Chrome 檔名不同的案例）。
測試從本機的原始位元組 HTTP 伺服器依序送出每個案例的標頭行與內容，透過 `<a>` 點擊觸發
下載，比較 Playwright 的 `download.suggested_filename` 與預期的檔名。多數案例送出一行
Content-Type、`X-Content-Type-Options: nosniff` 與二進位內容，排除 MIME sniffing；測 MIME
type 的案例自己列出標頭行與內容。

- **精確集合**（`exact_cases()`）：檔名由標頭與網址決定，Chromium 必須跟本套件全部一致，
  不一致就是失敗。
- **限制集合**（`limited_cases()`）：Chrome 會 sniff 內容來決定 MIME type 的回應。每個案例
  寫明本套件依宣告型別給的退路名字，以及 Chromium 對該內容給的名字；Chromium 必須開始下載、
  給出列出的名字，本套件必須給出列出的退路名字。案例屬於哪一組由人列出，不用本套件的 sniff
  判斷式決定。
- `browsers.yml` 的 `chromium` job 跑這兩組，是 required check（經由 aggregate job
  `browsers`）。
- **Firefox 和 WebKit 只出報告**：跟 Chrome 的檔名（精確集合是本套件的結果，限制集合是列出的
  Chromium 檔名）不一致記為 xfail，只有測試框架本身壞掉時才會失敗。`report` matrix 跑 Linux
  的 Firefox、Linux 的 WebKit，以及 macOS 的 WebKit（走 Apple 的網路程式碼，最接近 Safari）。
  每次執行的 job summary 與 artifact 就是文件〈行為與瀏覽器差異〉所說的差異清單。
- 語料在 `tests/browser/corpus.py`：每個案例的 id 必須唯一（`all_cases()` 會檢查），fuzz
  的 seed 固定，所以每次跑的案例都相同。伺服器原樣送出標頭值，值裡的 CR、LF、NUL 就是線上的
  位元組（`test_the_server_sends_the_header_lines_of_each_case_byte_for_byte` 會檢查），
  Chromium 照線上的標頭行讀。本套件逐值讀取，值裡換行之後的另一行標頭讀不到，空行之後的標頭行
  照樣讀，所以精確集合的案例不能讓這兩種行改變結果。從 Chromium 單元測試自動匯入的案例由
  `_unit_test_header_fits_one_line` 排除含 CR、LF、NUL 的值；換行、空行與 NUL 的案例逐案列在
  `RAW_LINE_CASES`。

Chromium 跟預期不一致時，先看報告裡的 Chromium 版本，判斷是移植的 bug，還是 Chromium
改了行為（限制集合的名字變了，代表 Chromium 的 sniffing 變了）；後者依〈跟進 Chromium〉處理，
不要為了讓測試通過去改測試的預期值。

## 升級 Playwright

Renovate 把 Playwright 獨立成 "Playwright reference browsers" 一組，永遠不自動合併：升級
Playwright 等於換掉比對的基準瀏覽器。

1. 看 Playwright release notes 裡附帶的 Chromium、Firefox、WebKit 版本。
2. 讓 Renovate PR 的 `browsers.yml` 跑完。`chromium` job 通過才能合併；失敗時依〈跟進
   Chromium〉判斷是 Chromium 改了行為還是 Playwright API 改了，處理完再合併。
3. Firefox／WebKit 報告的差異變多或變少都不擋合併。文件〈其他瀏覽器〉（`docs/en/behavior.md`
   與 `docs/zh-Hant/behavior.md`）寫著測量時的 Playwright 與瀏覽器版本、表格和一致的案例數，
   合併後用新的報告更新它們。

weekly canary 的 `newest-chromium` job 會先用最新的 Playwright 跑一次，讓這類變化提早出現。

## HTTP 函式庫測試

使用說明（`docs/*/usage.md`）教使用者怎麼把 httpx2、httpx、requests、aiohttp 和
`urllib.request` 的回應標頭交給本套件，文件也描述了這些函式庫本身的行為，例如用什麼
codec 解碼標頭、依名稱取標頭時給什麼、`response.url` 的主機名稱是什麼形式。`http-clients`
dependency group 裝這些第三方函式庫，以及 requests 底下的 urllib3（`dev` 也含它），
`tests/http_clients/` 檢查這些寫法與說法。沒有 `--with-http-clients` 時一律 deselect；給了
旗標卻缺這個 group 的任何一個套件時，pytest 直接報錯（`tests/conftest.py` 從
`pyproject.toml` 讀 group 的成員）：

```sh
uv sync
uv run pytest tests/http_clients --with-http-clients
```

- 本機伺服器逐位元組送出每個案例的標頭行（例如重複的 Content-Disposition、單行的逗號清單、
  沒關上的引號、舊式字元集與 UTF-8 的位元組、多行 Content-Type、X-Content-Type-Options、
  重新導向、折行與其他換行、NUL、過長或過多的標頭行），各函式庫照使用說明的寫法取回，結果
  必須等於把送出的標頭行原樣交給本套件的結果。使用說明說「會不同」的傳法（`response.headers`
  把重複的行接成一行、不帶 `headers_encoding` 的 Latin-1 字串），以及函式庫自己接折行、丟掉
  標頭行或拒收回應的地方（`LIBRARY_DIFFERENCES`），測試把不同的結果或丟出的例外寫成預期值。
  值裡另一行標頭與空行的案例另外檢查各函式庫照 Chromium 的方式切行或拒收，因為使用說明靠這一點
  說本套件逐值讀取的限制只影響自己組出的標頭行。
- aiohttp 有 C 與純 Python 兩種 HTTP parser（PyPy 或 `AIOHTTP_NO_EXTENSIONS=1` 時用後者）。
  測試在同一次執行裡換上兩種 parser 各跑一次；C parser 不存在時失敗，所以要在 CPython 上、
  用 aiohttp 針對那個 CPython 版本編譯的 wheel 跑。aiohttp 還沒替某個 CPython 版本出 wheel 時，
  會裝成純 Python 的 wheel，C parser 的測試就會失敗。
- CI 的 `http-clients` job 在 CPython 3.11 與 3.15 上跑它（見〈Python 支援窗〉）；weekly canary
  的 `newest-dependencies` 也帶這個旗標，用最新版的函式庫跑。

函式庫新版讓測試失敗時，先看它改了什麼：使用說明的寫法或說法不再成立，就改兩種語言的
使用說明（以及 README、api-reference 裡的同一件事）和測試；不要只改預期值讓測試通過，
預期值就是文件的說法。改使用說明裡的函式庫範例或說法時，同一個 commit 也改
`tests/http_clients/`。

## 跟進 Chromium

移植對象釘在一個 Chromium main 上的 revision：`scripts/generate_data.py` 的
`CHROMIUM_REVISION`、`CHROMIUM_COMMIT_POSITION`，以及該 revision 的 `DEPS` 釘的
`chromium/deps/icu` revision（`ICU_REVISION`）和它的 Unicode 版本（`UNICODE_VERSION`）。
generator 把這些值與產生的表格一起寫進 `src/browser_download_filename/_data.py`；
`_data.py` 不手改。

weekly canary 的 `chromium-drift` job 做兩件事：`generate_data.py --check` 確認
`_data.py` 仍是 generator 在釘選 revision 上的產物；`.github/scripts/chromium-drift.py`
比較 `TRACKED` 列出的 Chromium 檔案在釘選 revision 與 main 之間有沒有變動，以及 main 的
`DEPS` 是否換了 ICU。它失敗不會擋 dead-man's switch 的 ping（已發布的套件照常可用），但
Actions 會顯示失敗，要有人來看。

升級釘選 revision：

1. 選一個新的 Chromium main revision，記下它的 commit position，並從它的 `DEPS` 找出
   ICU revision。新 revision 不要比 Playwright 釘的 Chromium 新太多，否則瀏覽器測試比對的
   是舊行為。
2. 逐一檢視 `TRACKED` 檔案的變動：`chromium-drift` job 的 summary 會列出變動的檔案，連到
   GitHub mirror 上該檔案的 commit 歷史（例如
   `https://github.com/chromium/chromium/commits/main/net/http/http_content_disposition.cc`）。
   gitiles 的 `+log/<舊>..<新>/<路徑>` 也可以，但要先登入 Google 帳號才看得到歷史。
   各模組的 docstring 寫著它移植哪些 Chromium 檔案與函式，函式名稱也沿用 Chromium 的。
3. 把行為變動移植到對應模組，把新增或修改的單元測試案例移植進 `tests/test_chromium_*.py`。
   Chromium 有搬移或新增檔案時，同步更新 `chromium-drift.py` 的 `TRACKED` 與
   `THIRD-PARTY-LICENSES` 的檔案清單。
4. 更新 generator 的常數後重新產生資料：

   ```sh
   uv run --no-project --python 3.15 scripts/generate_data.py
   ```

   generator 會檢查 `unicodedata.unidata_version` 等於 `UNICODE_VERSION`。ICU 升到新的
   Unicode 版本、但還沒有 Python 支援時，先停在舊的 ICU，或等新 Python 的 beta。
5. 跑完整測試與 Chromium 瀏覽器測試，在 changelog（`docs/en` 與 `docs/zh-Hant`）寫明新的
   Chromium revision，以及檔名會因此改變的情況。

標頭行的讀法（`_http.py` 的 `locate_end_of_headers`、`assemble_raw_headers` 與 `_headers.py`
的 `line_value`）也是手寫的：升級釘選 revision 時，對照 `net/http/http_util.cc` 的
`LocateEndOfHeaders`、`AssembleRawHeaders`，`net/http/http_response_headers.cc` 的
`TryToCreate`／`HasEmbeddedNulls`，以及在 `net/http/http_stream_parser.cc` 呼叫它們的
`ParseResponseHeaders`（先找標頭結尾，再對這段標頭拒收 NUL、組行）。

MIME type 的推導（`_mime.py`）是手寫的，`generate_data.py --check` 不涵蓋它。升級釘選
revision 時，對照上游逐一重新檢查：可 sniff 的型別清單與 unknown 型別（`net/base/mime_sniffer.cc`
的 `kSniffableTypes`、`IsUnknownMimeType`）、X-Content-Type-Options 與 scheme 的判斷
（`ShouldSniffMimeType`）、URLLoader 不 sniff 時的轉換（`services/network/url_loader.cc`：空型別
與 feed 型別換成 `text/plain`），以及網路層的 MIME 解析（`net/http/http_response_headers.cc` 的
`GetMimeTypeAndCharset`、`net/http/http_util.cc` 的 `ParseContentType`、`net/base/mime_util.cc`
的 `ParseMimeType`）。這些來源檔也要列在 `chromium-drift.py` 的 `TRACKED` 裡，drift job 才看得到
它們的變動。

字元集的部分：單位元組表直接來自 ICU 的 `.ucm`；多位元組字元集用 Python 的 codec，
加上 generator 從 ICU 對照檔算出的修正（`MULTI_BYTE_OVERRIDE_*`、`MULTI_BYTE_REJECT_RUNS`）。
`test_charset.py` 會用 ICU 的狀態表列舉每個合法序列，把解碼結果的摘要跟
`MULTI_BYTE_DIGESTS` 比較，所以哪個 Python 版本的 CJK codec 一改，CI 就會在那個版本失敗。
處理方式是讓 generator 把差異也寫成修正，使結果不依賴 codec，而不是放寬測試。

## 發布

只有一條版本線：tag `vX.Y.Z` 發布 `browser-download-filename` 的 wheel 與 sdist 到 PyPI。
`.github/workflows/release.yml` 只接受精確符合 `^v[0-9]+\.[0-9]+\.[0-9]+$` 的 tag；保留
`workflow_dispatch`，但手動執行時也必須選取符合規則的 tag。`concurrency` 以完整 ref
分組，同一個 tag 一次只跑一個 release run。

1. 提升 `pyproject.toml` 的 `version`，執行 `uv lock` 同步 `uv.lock`（lock 裡有本專案自己的
   版本；CI 一律 `--locked`，沒同步會直接失敗），在 `docs/en/changelog.md` 與
   `docs/zh-Hant/changelog.md` 寫好這一版的內容與跟隨的 Chromium revision。
2. 經由 PR 把升版 commit 合併進 main（或由有 bypass 權限的管理者直接推送），等 main 上
   該 commit 的 `ci` 與 `browsers` 都綠，再對**同一個 commit** 打 tag 並推送。tag 不可移動、
   版本不可覆寫，內容有誤只能跳下一個版號。
3. release run 呼叫 `ci.yml`（`workflow_call`）建置並測試 wheel 與 sdist、產生 manifest、組成
   `release-batch`；同時呼叫 `browsers.yml`（`chromium-only: true`）再比對一次 Chromium。
   `verify-release-batch` 重驗 manifest 裡的 filename、SHA-256、source commit
   （必須等於 tag 指向的 commit）與版本（必須等於 tag）。
4. `publish-pypi` 在 protected environment `pypi` 執行，是唯一持有 `id-token: write` 的 job：
   先拒絕 rerun（`GITHUB_RUN_ATTEMPT` 必須是 1），再以單次、fail-closed 的 `pypi-has` 查詢
   要求該版本尚不存在（不重試，以免暫時查不到被誤判成安全），然後用 Trusted Publishing
   上傳整個 `release-batch/artifacts`（不用 API token，也不用 `skip-existing`）。
5. 上傳後，`pypi-set-matches` 對 PyPI 的 filename＋SHA-256 集合做有上限的輪詢：缺檔可等待
   傳播，多出檔案或 hash 不符立即失敗，逾時讓 job 失敗。

PyPI Trusted Publisher 必須綁定：owner `birdhackor`、repository
`browser-download-filename`、workflow filename **`release.yml`**、environment **`pypi`**。
專案尚未存在時用 pending publisher，填完全相同的值。GitHub environment `pypi` 的
deployment tag 規則只允許 `v*`。

repository 有兩個 ruleset：tag `v*` 禁止 update、delete 與 force-push，沒有 bypass
（immutable release tags）；`main` 要求 status checks `ci` 與 `browsers` 通過，並禁止刪除與
force-push，bypass：repo admin。

## 發布後與補救

1. 版本還沒寫進 PyPI 時（例如 publish 之前的 job 失敗），修好後用 `workflow_dispatch`
   選同一個 tag 開一個新的完整 run；不要重跑 publish job（它會拒絕）。
2. 版本已存在就拒發，絕不覆寫，也不用重建的產物補成同一個版本。內容錯誤或發布不完整時，
   在 PyPI 的管理介面 yank 該版本，提升版號、打新 tag，重新完整發布。

## Weekly canary 與 dead-man's switch

`.github/workflows/canary.yml` 每週三 03:41 UTC 執行（也可以 `workflow_dispatch`）：

- `published-package-on-newest-python`：`.github/scripts/pick-canary-python.py` 從
  setup-python 的 versions manifest 挑出這台 runner 可安裝、且為 beta 以上的最新 CPython，
  安裝 PyPI 上已發布的套件並做 smoke test。刻意不測 alpha。
- `newest-dependencies`：`uv lock --upgrade` 後帶 `--with-http-clients` 跑完整測試，提早發現
  pytest、Hypothesis 與 HTTP 函式庫等新版造成的問題。
- `newest-chromium`：只升級 Playwright，用它附帶的最新 Chromium 跑瀏覽器測試。
- `chromium-drift`：見〈跟進 Chromium〉。

前三個 job 都成功後，`ping-dead-mans-switch` 才會 POST 到 secret `HEALTHCHECKS_PING_URL`
（例如 healthchecks.io 的 ping URL）。外部服務的預期週期要設成一週以上並啟用逾期通知；
任何 canary 失敗、排程被停用或沒執行都不會 ping，外部服務因此會告警。GitHub 的
scheduled workflow 只在 default branch 執行，public repository 60 天沒有活動會被停用，
所以它不能是唯一的監測。healthchecks.io 的 check 在收到第一次 ping 前停在 New 狀態、
不會告警，設定或更換 endpoint 後要用 `workflow_dispatch` 手動跑一次 canary 並確認成功。

## Renovate

`renovate.json`：每週日 00:00–05:59（Asia/Taipei）開 PR；GitHub Actions 一律釘 digest。

- 只有 CI 基礎 Action（checkout、setup-python、download-artifact、upload-artifact）的
  非 major 更新會自動合併；setup-uv、PyPI 發布 Action、configure／deploy-pages 維持人工。
- uv（`setup-uv` 的 `version`，用 regex manager 追蹤）與 `uv_build` 合成一組 "uv toolchain"。
- Playwright 獨立一組，永不自動合併（見〈升級 Playwright〉）。
- aiohttp、httpx、httpx2、requests、urllib3 合成 "HTTP clients" 一組，不自動合併：
  `http-clients` job 檢查文件對它們的說法，但新版可能棄用文件叫使用者傳的屬性，或新增
  更合適的屬性，這兩種情況都不會讓測試失敗（見〈HTTP 函式庫測試〉）。
- pytest、Hypothesis、ruff、mypy、twine、zensical 合成 "Python development tools" 一組。

## 文件

`docs/en` 與 `docs/zh-Hant` 各自是一個 zensical 站（`zensical.en.toml`、
`zensical.zh-Hant.toml`），`.github/workflows/docs.yml` 在 main 的 `docs/**` 有變動時建置兩個
語言（`--strict`：連到不存在的頁面或 anchor 會讓建置失敗、不部署）、寫入根目錄的轉址頁，部署到 GitHub Pages（Settings → Pages 的 Source 是 GitHub Actions）。兩種語言的頁面一一對應；中文標題用
`{#...}` 指定跟英文相同的 anchor，讓兩邊的連結一致。本機預覽：

```sh
uvx --python 3.15 zensical==0.0.70 serve --config-file zensical.en.toml
```
