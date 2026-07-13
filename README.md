# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v2.2.0 是為 AI 輔助開發設計的輕量專案進度系統。每個要追蹤的 Git 專案只保留一個很小的 `.otcopulse`，讓 Agent 取得可靠進度時不必重新閱讀原始碼、歷史紀錄或所有專案報表。

![OctoPulse 資料流程](docs/octopulse-flow.svg)

## 設計理念

- **小型、明確的脈衝檔。** `.otcopulse` 是唯一的進度來源；空檔代表尚未初始化，非空檔必須符合嚴格 JSON schema，且上限為 4 KiB。
- **上下文預算優先。** 一般 Agent session 只讀取 Git root、輕量 Git 事實與目前專案的 marker。報表不會自動注入 prompt。
- **腳本產生彙總。** `octopulse portfolio report` 只尋找已登錄根目錄中的 marker，總覽只讀取專案快照；`auto` 僅在 marker、Git 輕量事實、legacy context 或活動指紋改變時刷新該專案。
- **明確且可逆的寫入。** 初始化、封存及注入 Agent 指引都要求明確指令；OctoPulse 不會修改或刪除 `PROJECT_STATUS.md` 與 `.ai/status.json`。專案報告可選擇唯讀、白名單擷取小型 `.ai/status.json` 作 legacy context。

## 安裝

安裝最新 GitHub Release。Codex、Antigravity 與 Grok Build 共用 `~/.agents/skills`；`auto` 模式會偵測已安裝的平台，但只安裝一份 shared global skill，避免同一個 loader 載入重複 skill。請選擇其一：

首次安裝，或保留既有 skill：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

更新既有 skill（會覆寫 `octopulse` skill）：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --force
```

只有在需要同時支援所有平台時，才在上述任一指令加上 `--agent all`；Codex、Antigravity 與 Grok Build 仍共用同一份 `~/.agents/skills/octopulse`：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent all
```

安裝器會驗證 release archive 的 SHA-256，並嘗試在 `~/.local/bin/octopulse` 建立 wrapper；此目錄通常已在 PATH。若該位置已有其他指令，安裝器不會覆寫，會改為輸出 `$OCTOPULSE_HOME/bin` 的 PATH 設定方式。再確認版本：

```sh
octopulse --version
```

Grok Build 可明確安裝 shared skill 與其原生 Stop hook；不會建立第二份 `~/.grok/skills`：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok
grok inspect
```

`grok inspect` 應顯示 `~/.agents/skills/octopulse` 與 `~/.grok/hooks/octopulse.json`。grok.com 網頁版 Skills 無法直接執行本機 `octopulse` CLI，並非本整合的支援範圍。

在 Grok Build 的非瑣碎工作開始與結束時，skill 會明確記錄最小活動事件：

```sh
octopulse activity start --tool grok
octopulse activity finish --tool grok --result updated
```

## 使用方式

### 追蹤正在維護的專案

在專案的 Git root 中執行：

```sh
octopulse init --yes
```

`init` 會建立空的 `.otcopulse`，並將 Git root 加入使用者的受信任掃描根目錄。人類已決定初始化時，不需要先執行 `context`；它是 AI skill 的唯讀診斷步驟。非瑣碎工作結束時，Agent 僅在目標、摘要、下一步、驗證或注意事項有實質變化時更新 marker，接著驗證：

```sh
octopulse validate .otcopulse
```

需要為專案加入持久化提醒時，明確指定 adapter；此動作才會以最小區塊更新 `AGENTS.md` 或 `CLAUDE.md`：

```sh
octopulse init --yes --agent codex
```

### 使用情境：由 AI Agent 讀取 skill

完成 global skill 安裝後，在已納管專案中直接告訴 Agent：「使用 OctoPulse skill 取得目前專案狀態，完成這項非瑣碎工作後更新 pulse 與專案報告。」Codex、Claude Code、Antigravity 或 Grok Build 會先執行：

```sh
octopulse context
```

若回傳 `valid`，skill 只讀取 `.otcopulse` 與輕量 Git 事實；工作開始與結束時，分別記錄不含 prompt 的工具事件：

```sh
octopulse activity start --tool codex
# Agent 完成工作；僅在語意狀態確實改變時更新 .otcopulse
octopulse validate .otcopulse
octopulse activity finish --tool codex --result updated
octopulse project report
```

`context` 與後續指令由 Agent 在同一輪 session 連續執行，不會形成兩個對話。若你的要求已明確表示「初始化 OctoPulse」且狀態為 `missing`，Agent 可在同一輪執行 `context` 後立即執行 `octopulse init --yes`。`uninitialized` 表示空 marker 已存在，不會重建；Agent 會等待你提供目標或在後續非瑣碎工作有明確事實時再建立語意狀態。只有你要求查看狀態、但結果為 `missing` 時，skill 才會先詢問是否建立 marker；`invalid` marker 的修復也一律先確認。不會掃描原始碼來猜測進度。跨專案總覽時，明確要求「使用 OctoPulse skill 產生所有納管專案的總報告」，skill 會在任何目錄執行 `octopulse portfolio report --refresh auto --explain`。

### 使用情境：人類或自動化直接執行

不使用 AI 時，仍可在專案 Git root 以 shell 或 CI 腳本執行相同流程。初始化後，由人類以編輯器維護 `.otcopulse`；只有狀態有實質變化才寫入並驗證：

```sh
octopulse init --yes
# 以編輯器更新 .otcopulse 的 goal、summary、next_action、verification 或 attention
octopulse validate .otcopulse
octopulse project report --lang zh-TW
```

需要留下開發工具活動時，明確包住一次非瑣碎作業；沒有使用 AI 時可省略這兩行：

```sh
octopulse activity start --tool claude
# 執行開發、測試或審查
octopulse activity finish --tool claude --result unchanged
```

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

在目前 repo 建立獨立且本機忽略的專案快照與報告：

```sh
octopulse activity start --tool codex
# 完成非瑣碎工作後
octopulse activity finish --tool codex --result updated
octopulse project report
```

產物位於 `.octopulse-reports/`，包含 `snapshot.json`、`latest.md`、`index.html` 與最小 `activity.jsonl`。專案報告只讀 marker、Git metadata、最近 10 筆 commit subject、活動事件與可選的小型 `.ai/status.json`；不讀取原始碼或 diff。`.otcopulse` 保持語意狀態唯一來源，legacy status 只作唯讀 context。

當安裝器偵測到 Codex 時，會自動遷移已知的 v1 `UserPromptSubmit` hook，改為兩個全域 v2 hooks：`SessionStart` 在 `startup|resume` 僅注入一次極短 skill 提醒；`Stop` 僅在有效、已註冊且非封存的專案更新已變更的報告。它們不讀 prompt、原始碼、diff 或對話，不寫 `.otcopulse` 或 activity。若要停用或移除，重新安裝時指定：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --without-codex-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --remove-codex-hooks
```

安裝器只自動遷移 `~/.codex/hooks.json` 的已知 v1 handler，保留其他 hooks。若舊設定位於 `config.toml`、plugin 或其他來源，請以 Codex `/hooks` 停用，因為多個來源的 hooks 都會執行。

Grok Build 使用獨立的 `~/.grok/hooks/octopulse.json`，只安裝 `Stop` hook。它只使用 hook JSON 的事件名稱與 `cwd`；僅在有效、已納管、非封存專案中增量刷新報告，不讀 prompt、原始碼、diff 或對話，亦不寫 marker 或 activity。Grok 的被動 hook 無法將 stdout 注入模型，因此不安裝 SessionStart hook。若要停用或移除：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --without-grok-hooks
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent grok --remove-grok-hooks
```

### 總報告

```sh
octopulse portfolio report --refresh auto --explain
```

此命令可在任意目錄執行。它只刷新指紋已變更的專案快照，再彙整 `$OCTOPULSE_HOME/reports` 的 `projects.json`、`latest.md` 與 `index.html`。HTML 可切換總覽／個別專案，並以 URL 語言參數切換中文與英文介面；使用者寫入的目標與摘要維持原文。

## `.otcopulse` 格式

marker 是空檔或不超過 4 KiB 的 UTF-8 JSON。完整定義請見 [schema](schemas/otcopulse.schema.json)。

```json
{
  "schema_version": 2,
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
  "attention": []
}
```

## 命令參考

| 命令 | 用途 |
| --- | --- |
| `octopulse context` | 唯讀檢查目前 Git 專案與 marker 狀態。 |
| `octopulse init --yes` | 建立空 marker 並登錄根目錄。 |
| `octopulse archive --yes --reason TEXT` | 封存專案為 `paused` / `stale`。 |
| `octopulse activity start\|finish --tool TOOL` | 記錄非瑣碎 AI 工具活動，不含 prompt。 |
| `octopulse hook codex-session-start\|codex-stop` | 供 Codex lifecycle hook 使用；不可手動用於推測專案狀態。 |
| `octopulse hook grok-stop` | 供 Grok Build Stop hook 使用；不可手動用於推測專案狀態。 |
| `octopulse project report` | 產生目前 repo 的專案快照、Markdown 與 HTML。 |
| `octopulse portfolio report --refresh auto` | 在任意目錄產生所有納管專案總報告。 |
| `octopulse validate .otcopulse` | 驗證 marker schema 與大小。 |
| `octopulse root add\|list\|remove PATH` | 管理受信任的掃描根目錄。 |
| `octopulse report` | `portfolio report` 的相容別名。 |

## 文件語言

本檔為繁體中文主文件；[README.en.md](README.en.md) 是對應英文版本。功能、指令、範例與流程變更必須在同一個 commit 同步更新兩份 README；CLI、檔名與 schema 欄位一律維持英文。
