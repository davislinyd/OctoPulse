# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v3.2.0 是為 AI 輔助開發設計的輕量專案進度系統。每個要追蹤的 Git 專案只保留一個很小的 `.octopulse`，讓 Agent 取得可靠進度時不必重新閱讀原始碼、歷史紀錄或所有專案報表。

![OctoPulse 資料流程](docs/octopulse-flow.svg)

## 設計理念

- **小型、明確的脈衝檔。** `.octopulse` 是唯一的進度來源；空檔代表尚未初始化，非空檔必須符合嚴格 JSON schema，且上限為 4 KiB。
- **上下文預算優先。** 一般 Agent session 只讀取 Git root、輕量 Git 事實與目前專案的 marker。報表不會自動注入 prompt。
- **模型無關的交接。** handoff 只保存最新的工具、Git 變更檔名、必讀檔案與短決策；不保存 prompt、對話、diff 或檔案內容。
- **自動追溯，不存對話文字。** Stop hook 增量讀取 Git 歷史、AI 工具的 transcript 與 marker 的下一步，寫入本機 `.octopulse-reports/journal.jsonl`。對話只擷取待辦工具的項目、時間、回合數、工具呼叫次數、專案內被編輯的檔名，以及是否執行 `git commit`；不保存 prompt、回覆、指令、工具輸出或 diff。整個過程由腳本完成，不消耗模型 token。
- **腳本產生彙總。** `octopulse portfolio report` 只尋找已登錄根目錄中的 marker，總覽只讀取專案快照；`auto` 僅在 marker、Git 輕量事實、legacy context 或活動指紋改變時刷新該專案。
- **明確且可逆的寫入。** 初始化、封存及注入 Agent 指引都要求明確指令；OctoPulse 不會修改或刪除 `PROJECT_STATUS.md` 與 `.ai/status.json`。專案報告可選擇唯讀、白名單擷取小型 `.ai/status.json` 作 legacy context。

## 安裝

安裝最新 GitHub Release。每個工具只裝一份到自己的目錄：Claude Code 是 `~/.claude/skills/octopulse`，Codex 是 `~/.codex/skills/octopulse`，Grok Build 是 `~/.grok/skills/octopulse`，Antigravity 是 `~/.agents/skills/octopulse`。Codex 也會讀 `~/.agents/skills` 且不去除同名 skill，所以安裝 Codex 時不會再裝 `~/.agents` 那份。`auto` 模式會偵測已安裝的平台。請選擇其一：

首次安裝，或保留既有 skill：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

更新既有 skill（會覆寫 `octopulse` skill）：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --force
```

只有在需要同時支援 Claude Code、Codex 與 Grok Build 時，才在上述任一指令加上 `--agent all`。Antigravity 需另外以 `--agent antigravity` 安裝；若同一台機器也用 Codex，Codex 會看到兩份 skill：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent all
```

安裝器會驗證 release archive 的 SHA-256，並嘗試在 `~/.local/bin/octopulse` 建立 wrapper；此目錄通常已在 PATH。若該位置已有其他指令，安裝器不會覆寫，會改為輸出 `$OCTOPULSE_HOME/bin` 的 PATH 設定方式。再確認版本：

```sh
octopulse --version
```

Grok Build 可明確安裝原生 skill 與 Stop hook。Grok 會依名稱合併 `~/.grok`、`~/.agents`、`~/.claude` 的同名 skill，因此和 Claude Code 那份並存不會重複：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok
grok inspect
```

`grok inspect` 應顯示 `~/.grok/skills/octopulse` 與 `~/.grok/hooks/octopulse.json`。grok.com 網頁版 Skills 無法直接執行本機 `octopulse` CLI，並非本整合的支援範圍。

在 Grok Build 讀取進度，並在語意狀態改變時寫回：

```sh
octopulse status
octopulse update --tool grok --summary "..." --next "..."
```

`update` 會驗證 marker、記一筆 finish，並刷新專案報告。`activity start|finish` 仍可單獨使用。

## 使用方式

### 從 v2 升級

v3 只辨識 `.octopulse`。已使用 v2 `.otcopulse` 的專案，更新 CLI 後在每個專案 Git root 明確執行一次：

```sh
octopulse migrate-marker --yes
```

此命令只在同一目錄原子重新命名 marker，不讀取或改寫其內容，也不讀取原始碼、Git history 或 legacy status。兩種 marker 同時存在時會拒絕操作；新 marker 已存在或兩者皆不存在時安全回報結果。安裝器不會自動遷移任何專案。

### 從 marker schema v2 升級

新版 CLI 將有效的 schema v2 marker 回報為 `migration_required`，仍可唯讀產生報告，但不可建立 handoff。先更新所有開發環境的 OctoPulse CLI 與 skill，再在每個要交接的專案明確執行：

```sh
octopulse migrate-schema --yes
```

此命令只將 marker 升級為 schema v3 並加入 `"handoff": null`；不讀取原始碼、對話或 Git history。

### 追蹤正在維護的專案

在專案的 Git root 讀取目前進度：

```sh
octopulse status
```

第一次寫入語意狀態：

```sh
octopulse update --yes --goal "Ship the current milestone." --next "Open the pull request."
```

`update --yes` 會建立有效的 `.octopulse`、註冊 Git root，並在寫入前驗證。若 marker 已是 schema v2，同一個命令會把它升到 v3、保留原有欄位並註冊根目錄。每次成功寫入都會刷新專案報告與總覽。之後只帶要改的欄位：

```sh
octopulse update --summary "The current work is verified locally." --next "Open the pull request."
```

對 Agent 說「我要將專案進度更新到 OctoPulse」時，它會在同一輪完成上面的設定，不再另問一次。寫完即可打開兩個報告：目前專案的 `.octopulse-reports/index.html`，以及所有已註冊專案的 `~/.config/octopulse/reports/index.html`。此後 Codex、Claude Code 與 Grok 的 Stop hook 會在這個已納管專案的後續回合自動刷新報告。

`init --yes` 仍可建立空 marker。需要持久化提醒時，才用 `--agent` 更新 `AGENTS.md` 或 `CLAUDE.md`：

```sh
octopulse init --yes --agent codex
```

### 使用情境：由 AI Agent 讀取 skill

完成 global skill 安裝後，告訴 Agent：「使用 OctoPulse skill 讀取目前專案狀態；若這項工作改變目標、摘要、下一步、驗證或注意事項，用 update 寫回。」Agent 先執行：

```sh
octopulse status
```

狀態為 `valid` 時，以這份輸出為進度。換模型時才讀取交接：

```sh
octopulse handoff show
```

`handoff show` 會輸出不超過 marker 上限的 resume packet。接手模型只讀取 `read_first` 指定檔案與必要 Git 變更，不可為恢復上下文掃描整個專案；資訊仍不足時才擴大範圍。工作結束且語意狀態有變時：

```sh
octopulse update --tool codex --summary "The marker write path is verified." --next "Commit the pulse with the work."
```

這次 `update` 會驗證 marker、記一筆 finish，並刷新專案報告。換模型前另執行 `octopulse handoff create`。`activity start|finish` 與單獨的 `validate` 仍可使用，但不是預設收尾。

跨裝置切換時，將 `.octopulse` 與程式變更一併 commit 並 push。`handoff show` 若偵測到未提交的 marker，會明確警告它只可在本機交接。各平台的完整對話由該平台自行保存，OctoPulse 不複製或同步對話。

沒有明確要求更新進度時，Agent 只檢視報告：目前專案用 `octopulse status`，所有納管專案用 `octopulse portfolio report --refresh auto --explain`。它不會詢問 goal 或 next，也不會寫 marker。若要求是把專案進度更新到 OctoPulse，Agent 在同一輪執行 `octopulse update --yes --tool <目前工具>`；使用者有說明的 goal、summary、next 才帶入，沒說的使用預設文字。schema v2 也用同一個命令升級。`invalid` 的修復一律先確認。跨專案總覽時，skill 會在任何目錄執行 `octopulse portfolio report --refresh auto --explain`。

### 使用情境：人類或自動化直接執行

不使用 AI 時，在專案 Git root 執行：

```sh
octopulse status
octopulse update --summary "..." --next "..."
octopulse project report --lang zh-TW
```

要一併留下工具活動時，把 `--tool` 加在 `update` 上。沒有使用 AI 時省略 `--tool`。

在任何目錄產生總覽，或在 CI 中指定輸出位置：

```sh
octopulse portfolio report --refresh auto --output ./octopulse-portfolio
```

### 封存過舊專案

不再維護、但仍要出現在總覽的專案，不需要讀取原始碼或舊狀態檔：

```sh
octopulse archive --yes --reason "Superseded by the new platform."
```

這會寫入有效的 `phase: paused`、`health: stale` marker，記錄封存原因與明確的重新啟動條件。完全不需追蹤的舊專案不應建立 marker，也不應加入掃描根目錄。

### 專案報告與 AI 工具活動

Claude Code 與 Codex 的 Stop hook 會自動把 session 內以 `git commit` 建立的提交連到該對話編號。沒有自動連結時（例如未安裝 hook），可手動記在本機，不寫進 commit：

```sh
octopulse session record --commit HEAD --tool claude --session "$SESSION_ID"
```

報告會在該提交旁顯示工具名稱。有對話編號時，「打開對話」會透過 `octopulse://resume?commit=<sha>` 在這台電腦恢復該對話。這個紀錄在 `.ai/octopulse-sessions.jsonl`，不會被 push。

`octopulse update --tool codex` 會記一筆 finish，並刷新目前 repo 的專案報告與總覽。成功寫入 marker 時也會刷新這兩份報告。也可以分開執行：

```sh
octopulse activity finish --tool codex --result updated
octopulse project report
```

產物位於 `.octopulse-reports/`，包含 `snapshot.json`、`latest.md`、`index.html`、最小 `activity.jsonl` 與 `journal.jsonl`。專案報告只讀 marker、Git metadata、最近 20 筆 commit subject、活動事件、journal 與可選的小型 `.ai/status.json`；不讀取原始碼或 diff。`.octopulse` 保持語意狀態唯一來源，legacy status 只作唯讀 context。

當安裝器偵測到 Codex 時，會自動遷移已知的 v1 `UserPromptSubmit` hook，改為兩個全域 v3 hooks：`SessionStart` 在 `startup|resume` 注入一次極短 skill 提醒；`Stop` 僅在有效、已註冊且非封存的專案更新已變更的報告。它們讀取 `hook_event_name` 與 `cwd`；`Stop` 另讀 `session_id` 與 `transcript_path` 來更新 journal（見「開發記錄與待辦」）。它們不保存 prompt 或回覆，不讀原始碼或 diff，不寫 `.octopulse` 或 activity。若要停用或移除，重新安裝時指定：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --without-codex-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --remove-codex-hooks
```

安裝器只自動遷移 `~/.codex/hooks.json` 的已知 v1 handler，保留其他 hooks。若舊設定位於 `config.toml`、plugin 或其他來源，請以 Codex `/hooks` 停用，因為多個來源的 hooks 都會執行。

Claude Code 會把同一組行為併入既有的 `~/.claude/settings.json`，保留檔案裡的其他設定與 hooks。`SessionStart` 的 matcher 是 `startup|resume|clear|compact|fork`，stdout 使用 Claude 會讀取的 `hookSpecificOutput.additionalContext`。`Stop` 更新 journal 並刷新報告，不回傳會擋住結束的 `additionalContext`。若要停用或移除：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent claude --without-claude-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent claude --remove-claude-hooks
```

Grok Build 使用獨立的 `~/.grok/hooks/octopulse.json`，只安裝 `Stop` hook。目前的 stdin 同時帶有 `hook_event_name: "Stop"` 與 `hookEventName: "stop"`；handler 兩種都接受，並且只使用 `cwd`。它僅在有效、已納管、非封存專案中增量刷新報告，不讀 prompt、原始碼、diff 或對話，亦不寫 marker 或 activity。Grok 的 `SessionStart` stdout 不會進入模型，因此不安裝 SessionStart hook，也不在 `Stop` 回傳會讓回合繼續的 `additionalContext`。若要停用或移除：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --without-grok-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --remove-grok-hooks
```

### 開發記錄與待辦

已納管、非封存的專案在每次 Claude Code、Codex 或 Grok 回合結束時，由 Stop hook 自動更新本機 journal（`.octopulse-reports/journal.jsonl`，不進 Git）：

- **Git：** 只處理上次之後的新 commit，記錄 subject、conventional commit 類型與 scope、增刪行數、檔案數。commit body 中 `TODO:`、`FIXME:`、`Follow-up:` 開頭的行會成為待辦；之後的 commit subject 提到同一件事時視為完成。不讀 diff 內容。
- **AI 對話：** 只接受 `~/.claude/projects` 與 `~/.codex/sessions` 下的一般檔案，依位移只讀新增部分（每次上限 2 MiB）。擷取 Claude `TaskCreate`/`TaskUpdate`/`TodoWrite` 與 Codex `update_plan` 的待辦、回合數、工具呼叫次數、專案內被編輯的檔名，以及是否執行 `git commit`（用來自動連結提交與對話）。待辦文字會遮罩疑似金鑰。Grok 只走 Git 與 marker。
- **Marker：** `next_action` 變更時記一筆。

journal 最多 1000 筆、保留 180 天。Agent 平常只多看到 `octopulse status` 的一行摘要，需要追溯時再查：

```sh
octopulse log --limit 10   # 最近的開發記錄
octopulse todo             # 目前未完成的待辦
octopulse journal ingest   # 沒有 hook 時手動更新 Git 與 marker 記錄
```

### 總報告

```sh
octopulse portfolio report --refresh auto --explain
```

此命令可在任意目錄執行。它只刷新指紋已變更的專案快照，再彙整 `$OCTOPULSE_HOME/reports` 的 `projects.json`、`latest.md` 與 `index.html`。HTML 可切換總覽／個別專案，並以 URL 語言參數切換中文與英文介面；使用者寫入的目標與摘要維持原文。

## `.octopulse` 格式

marker 是空檔或不超過 4 KiB 的 UTF-8 JSON。完整定義請見 [schema](schemas/octopulse.schema.json)。

```json
{
  "schema_version": 3,
  "name": "Example Project",
  "last_updated": "2026-07-12T10:00:00+08:00",
  "phase": "implementation",
  "health": "active",
  "goal": "Ship the current milestone.",
  "summary": "The current work is verified locally.",
  "next_action": "Open the pull request.",
  "verification": {
    "status": "passed",
    "last_command": "python3 -m unittest",
    "last_verified_at": "2026-07-12T10:00:00+08:00"
  },
  "attention": [],
  "handoff": {
    "tool": "codex",
    "created_at": "2026-07-12T10:00:00+08:00",
    "commit": "0123456789abcdef",
    "worktree_files": ["octopulse/core.py"],
    "read_first": ["octopulse/core.py"],
    "decisions": ["Keep the marker under 4 KiB."]
  }
}
```

## 命令參考

| 命令 | 用途 |
| --- | --- |
| `octopulse` / `octopulse status` | 印出目前專案的進度。`--json` 給 Agent，`--lang en` 印英文。 |
| `octopulse update` | 建立或修補 marker。缺檔或空檔時 `--yes` 即可，沒有帶的 goal 與 next 使用預設文字。`--yes` 也會把 schema v2 升到 v3，並刷新兩個報告。 |
| `octopulse context` | 唯讀檢查目前 Git 專案與 marker 狀態。 |
| `octopulse init --yes` | 建立空 marker 並登錄根目錄。 |
| `octopulse migrate-marker --yes` | 將同一 Git root 的 v2 `.otcopulse` 原子改名為 `.octopulse`。 |
| `octopulse migrate-schema --yes` | 明確將有效的 schema v2 marker 升級為 v3。 |
| `octopulse handoff create\|show` | 寫入最新交接，或讀取 token 受限的 resume packet。 |
| `octopulse archive --yes --reason TEXT` | 封存專案為 `paused` / `stale`。 |
| `octopulse activity start\|finish --tool TOOL` | 記錄非瑣碎 AI 工具活動，不含 prompt。 |
| `octopulse hook codex-session-start\|codex-stop` | 供 Codex lifecycle hook 使用；不可手動用於推測專案狀態。 |
| `octopulse hook claude-session-start\|claude-stop` | 供 Claude Code lifecycle hook 使用；不可手動用於推測專案狀態。 |
| `octopulse hook grok-stop` | 供 Grok Build Stop hook 使用；不可手動用於推測專案狀態。 |
| `octopulse log [--limit N] [--json]` | 印出最近的 journal 事件（提交、對話、待辦清單、下一步）。 |
| `octopulse todo [--json]` | 印出目前未完成的待辦（下一步、AI 待辦清單、commit 待辦）。 |
| `octopulse journal ingest` | 立即把新 commit 與 marker 變更寫入 journal。 |
| `octopulse project report` | 產生目前 repo 的專案快照、Markdown 與 HTML。 |
| `octopulse portfolio report --refresh auto` | 在任意目錄產生所有納管專案總報告。 |
| `octopulse validate .octopulse` | 驗證 marker schema 與大小。 |
| `octopulse root add\|list\|remove PATH` | 管理受信任的掃描根目錄。 |
| `octopulse report` | `portfolio report` 的相容別名。 |

## 文件語言

本檔為繁體中文主文件；[README.en.md](README.en.md) 是對應英文版本。功能、指令、範例與流程變更必須在同一個 commit 同步更新兩份 README；CLI、檔名與 schema 欄位一律維持英文。
