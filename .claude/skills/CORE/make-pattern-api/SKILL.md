---
name: make-pattern-api
description: 定義一般 DE/DV engineer 透過 make 新增、驗證、執行、列出與註冊 pattern 的真實 User API（依實際 Makefile 為準，不得臆造 target 名稱）。
allowed-tools: Read Grep Glob Edit Write PowerShell
---
# Make Pattern User API

UVM environment 必須允許使用者透過 make 管理 pattern。

BUG FIX (2026-09-01): 本檔先前列出的 11 個 target
(`add-pattern` / `validate-pattern` / `list-patterns` / `show-pattern` /
`run-pattern` / `verify-pattern` / `regression-add` / `regression-remove` /
`regression` / `regression-monitor` / `regression-report`) **不存在於** 產生出來的
UVM sim environment 的真實 Makefile
(`dv_harness/uvm_generator/templates/sim_scripts/Makefile`)。任何 agent 若對著
一個 generator 產生的 sim environment 執行 `make add-pattern` 之類指令，會得到
`make: *** No rule to make target 'add-pattern'` 的真實失敗。

同一組名稱（hyphen 版本）其實是**另一個、範圍不同**的真實系統：
`.claude/templates/Makefile.patterns.mk`（供專案自己的頂層 Makefile 手動
`include`，操作對象是 `.dv-harness/` 底下的 pattern registry / regression
bookkeeping，不是某一個 generator 產生出來的 IP-level sim environment）。這兩
層系統目前是分開的、都是真的，但**互不相通**：`Makefile.patterns.mk` 裡對應
實際模擬執行的幾個 target（`run-pattern` / `verify-pattern` / `regression` /
`regression-monitor` / `regression-report`）目前只是 stub echo，尚未 wiring 到
下面第一節的真實 sim Makefile 或 `dv_harness/lsf_client.py`。使用本 skill 前，
先確認你當下操作的是哪一層，不要把兩層的 target 混用。

---

## 第一層：generator 產生的 sim environment Makefile（實際跑 VCS/LSF 的那一個）

來源：`dv_harness/uvm_generator/templates/sim_scripts/Makefile`（~3650 行，
protocol-parameterized template）。真實 target 名稱與語意如下，均以該檔
`help:` target 的輸出為準（唯一可信來源，模擬使用者實際會看到的說明）：

| 用途 | 真實 target |
|---|---|
| 產生 synopsys_sim.setup 及目錄 | `make setup` |
| Stage 1a/1b/1c 分析（UVM lib / DUT / testbench） | `make analyze_uvm` / `make analyze_dut` / `make analyze_tb`（`analyze` 是 `analyze_tb` 的 alias） |
| Stage 2：elaborate，產生 simv | `make elab` |
| Build simv（依 `FLOW=onestep\|fourstep`） | `make compile` |
| 執行單一 pattern（會先確保 build） | `make sim PATTERN=<name>` |
| 執行單一 pattern，**不 build**（LSF job 用這個） | `make run PATTERN=<name>` |
| 加 `+fsdb` 執行後開 Verdi | `make debug PATTERN=<name>` |
| 對既有 FSDB 開 Verdi | `make verdi PATTERN=<name>` |
| 整個 suite 跑 regression（`JOBS=<n>` 本機平行，或 `LSF=1` 上 farm） | `make regress SUITE=all\|list\|<suite>` |
| 重印上一次 regression 的結果 | `make regress_summary` |
| LSF：查活著的 job / 印 summary（不重跑）/ kill / 查 queue | `make lsf_status` / `make lsf_report` / `make lsf_kill` / `make lsf_queues` |
| Crash 後手動收集某次 run 的 VIP report | `make collect_reports` |
| 註冊 / 取消註冊一個 pattern（transactional，失敗自動回復） | `make ADD_PAT PAT_NAME=<f>.txt PAT_DIR=<d>` / `make RM_PAT PAT_NAME=<f>.txt PAT_DIR=<d>` |
| 依 suite 分類列出所有已註冊 pattern | `make list_patterns`（**底線**，不是 `list-patterns`） |
| Coverage：urg report / 合併 vdb / Verdi coverage GUI | `make cov` / `make cov_merge COV_DIRS=<list>` / `make cov_gui` |
| 靜態檢查（include order、pattern framework 規則、Makefile 展開順序、macro 自足性、zero-delay loop、register field audit、VIP class/enum 可用性、VIP path 是否跑出 VIP_HOME）——秒級，長 build 前先跑 | `make check` |
| 清理 | `make clean` / `make distclean` |
| 列出以上全部 + 目前變數值 | `make help` |

沒有獨立的 `show-pattern` / `run-pattern` / `verify-pattern` target：
- 「show 一個 pattern 的資訊」→ `make list_patterns` 會依 suite 印出全部已註冊
  pattern；沒有單一 pattern 的專屬 show 指令，要看某個 pattern 屬於哪個 suite
  可以直接讀 registry 檔（見下方目錄慣例）或用 grep。
- 「run 一個 pattern」→ 就是 `make sim PATTERN=<name>`（會 build）或
  `make run PATTERN=<name>`（不 build，假設 simv 已存在）。
- 「verify 一個 pattern」→ **沒有單一個真實 target 對應**。目前能做的組合是：
  `make check`（靜態檢查，秒級，跑在整個 tb 上而非單一 pattern）
  + `make sim PATTERN=<name>`（動態跑一次）
  + 看 log 裡的 `SvtTestEpilog` 與 `record_result`/`RECORD=1` 的判定結果
    （PASS 才會被加進 `regression.list`，FAIL 會被移除，見下方）。
  如果需要「validate-pattern」這種一鍵動作，目前這個真實 Makefile 沒有提供，
  不要臆造一個新 target 名稱去填這個空缺。

常用變數（完整列表見 `make help`，這裡列最常用的）：

- `PATTERN=<name>`：要跑的 pattern
- `SEED=<n>`：random seed
- `WAVE=0|1|full`：FSDB 開關（0=off，1=target-IP blocks，full=整個 SoC），run-time only
- `FSDB_START=<ns>` / `FSDB_STOP=<ns>`：只錄一段視窗
- `PA=0|1`：Protocol Analyzer（需要 `VERDI_HOME`）
- `COV=0|1` / `FCOV=0|1`：VCS code coverage / VIP functional coverage（* 會強制 rebuild）
- `SUITE=all|list|<name>`：`regress` 要跑哪一組；`list` = `regression.list` 裡的內容
- `RECORD=0|1`：這次 run 的結果是否更新 `regression.list`（PASS 加入、FAIL 移除，預設 0）
- `JOBS=<n>`：`regress` 時同時跑幾個 pattern（分享同一個已 elaborate 的 simv）
- `NPROC=<n>`：build 平行度（跟 `JOBS` 是兩件事）
- `LSF=0|1|int`：0 本機、1 batch、int interactive（會一次設好 `LSF_COMPILE`/`LSF_SIM`/`LSF_VERDI`）
- `LSF_QUEUE=` / `LSF_JOBS=` / `LSF_TIMEOUT=` / `LSF_NCORE=` / `LSF_MEM=` 等：LSF 細項，見 `make help`

Pattern 目錄與 registry 慣例（以此 Makefile 的 `ADD_PAT`/`RM_PAT`/`PATTERN_LIST`
定義為準，取代原本文件臆造的 `pattern.yaml`/`options.f` 版面——這兩個檔案在
真實 Makefile 裡不存在）：

```
$(UVM_ROOT_PATH)/tb/patterns/<suite>/<pattern_name>.txt   # command.txt 內容本體
$(UVM_ROOT_PATH)/tb/patterns/pattern_list.txt             # registry：name suite [file]
$(UVM_ROOT_PATH)/tb/patterns/dv_uvm_pattern_pool.svh      # 由 registry 產生，勿手改
$(UVM_ROOT_PATH)/regression.list                          # 目前已知會過的 pattern 清單
```

`suite` 名稱不是 hardcode 的固定清單，是從 `pattern_list.txt` 第二欄動態算出來
的（`SUITE_NAMES`）；一個 suite 若解析出 0 個 pattern 會被視為錯誤，不會安靜地
跑 0 個 test。

新增 pattern 的真實流程（取代原本臆造流程中不存在的步驟）：

1. 把 `command.txt`（新檔名）放進 `tb/patterns/<suite>/<name>.txt`
2. `make ADD_PAT PAT_NAME=<name>.txt PAT_DIR=<suite>` —— 會先確認檔案存在，
   再把一行寫進 `pattern_list.txt` 並重新產生 `dv_uvm_pattern_pool.svh`；
   失敗（例如名稱與既有 pattern 衝突）會自動把 registry 復原，不會留下半殘檔。
3. `make check` —— 秒級靜態檢查（include order / pattern 規則 / VIP class 與
   enum 可用性 等），在真的花時間 build 之前先擋掉明顯錯誤。
4. `make sim PATTERN=<name>` —— 真的跑一次模擬，看 log 裡 `SvtTestEpilog` 判定
   結果。
5. 若要讓這次結果影響 regression 清單：加上 `RECORD=1`
   （`make sim PATTERN=<name> RECORD=1`）——PASS 會把 pattern 加進
   `regression.list`，FAIL 會把它移除。
6. 需要移除某個已註冊 pattern 時用 `make RM_PAT PAT_NAME=<name>.txt PAT_DIR=<suite>`
   （只取消註冊，不刪檔案；若原本在 `regression.list` 裡也會一併移掉）。

---

## 第二層：harness 層級 pattern registry / regression bookkeeping（另一個真實系統，範圍不同）

來源：`.claude/templates/Makefile.patterns.mk`（設計上是給專案自己的頂層
Makefile `include` 用的片段，不是某個 generator 產生出來的 sim environment的
一部分）。這一層操作的是 `.dv-harness/` 底下的 pattern registry
（`PATTERNS_JSON` -> `tools/generate_pattern_registry.py` ->
`PATTERN_REGISTRY_OUT`）與 `.dv-harness/regression.list`
（`tools/regression_list_cli.py`），跟第一層 sim Makefile 自己的
`tb/patterns/pattern_list.txt` 與 `$(UVM_ROOT_PATH)/regression.list` 是**兩份
不同的檔案**。

| Target | 狀態 | 實際行為 |
|---|---|---|
| `make add-pattern` | 真實 | 呼叫 `tools/generate_pattern_registry.py`，用 `PATTERNS_JSON` 重新產生並驗證 registry |
| `make validate-pattern` | 真實 | 呼叫 `tools/verification_flow/pattern_registry_completeness_gate.py` 對 registry 做 completeness gate |
| `make list-patterns` | 真實 | `cat` 已產生的 `pattern_list.txt` |
| `make show-pattern PATTERN=<name>` | 真實 | 在 `pattern_list.txt` 裡 grep 該 pattern |
| `make regression-add PATTERN=<name>` | 真實 | 呼叫 `tools/regression_list_cli.py record-verdict --passed` |
| `make regression-remove PATTERN=<name>` | 真實 | 呼叫 `tools/regression_list_cli.py record-verdict --failed` |
| `make run-pattern` | **Stub** | 只 `echo`，尚未接上真的 VCS/simulator 呼叫 |
| `make verify-pattern` | **Stub** | 只 `echo`，"project-specific: not modeled generically" |
| `make regression` | **Stub** | 只 `echo`，尚未接上 `dv_harness/lsf_client.py` 的 `bsub_submit` |
| `make regression-monitor` | **Stub** | 只 `echo`，尚未接上 `bjobs_query` |
| `make regression-report` | **Stub** | 只 `echo`，尚未接上 `dv_harness/regression_reporter.py` |

這五個 stub target 執行時**不會報錯**（不是 "no rule to make target"），但也
**不會真的跑模擬、不會真的送 LSF、不會真的產報告**——只會印出一行提示。對
agent 而言這比直接失敗更危險：容易誤判成「已經跑過了」。目前若要真的
build/run/regress，必須直接對 generator 產生的 sim environment 下第一層的
真實指令（`make compile` / `make sim PATTERN=` / `make regress`），不要依賴這
五個 stub target。

---

## 使用這份文件時的判斷原則

1. 先確認自己在哪一層：如果目標是「對一個已產生的 UVM sim environment 下指令
   跑模擬/regression」，用第一層（`sim_scripts/Makefile` 的真實 target）。
   如果目標是「維護 harness 專案層級的 pattern registry / regression 清單，
   且該專案的頂層 Makefile 確實有 `include .claude/templates/Makefile.patterns.mk`」，
   才用第二層。
2. 不要把兩層的 target 名稱套用到另一層（例如不要對 sim environment 下
   `make add-pattern`，也不要期待 harness 層的 `make regression` 真的會送
   模擬——目前它是 stub）。
3. 若不確定某個 target 是否存在，先用
   `grep -n "^[a-zA-Z_][a-zA-Z0-9_.-]*:" <該層的 Makefile>` 或該 Makefile 自己
   的 `make help` 目標確認，不要憑記憶或憑本文件的舊版本臆造名稱。
