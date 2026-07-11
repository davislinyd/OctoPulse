# OctoPulse

[繁體中文](README.md) · [English](README.en.md)

OctoPulse v2.0.1 是為 AI 輔助開發設計的輕量專案進度系統。每個要追蹤的 Git 專案只保留一個很小的 `.otcopulse`，讓 Agent 取得可靠進度時不必重新閱讀原始碼、歷史紀錄或所有專案報表。

![OctoPulse 資料流程](docs/octopulse-flow.svg)

## 設計理念

- **小型、明確的脈衝檔。** `.otcopulse` 是唯一的進度來源；空檔代表尚未初始化，非空檔必須符合嚴格 JSON schema，且上限為 4 KiB。
- **上下文預算優先。** 一般 Agent session 只讀取 Git root、輕量 Git 事實與目前專案的 marker。報表不會自動注入 prompt。
- **腳本產生彙總。** `octopulse report` 只尋找已登錄根目錄中的 marker，並以指紋快取避免內容未變時重寫 JSON、Markdown 或 HTML。
- **明確且可逆的寫入。** 初始化、封存及注入 Agent 指引都要求明確指令；OctoPulse 不會讀取、修改或刪除 `PROJECT_STATUS.md` 與 `.ai/status.json`。

## 安裝

安裝最新 GitHub Release。Codex 與 Antigravity 共用 `~/.agents/skills`；`auto` 模式只會安裝一份已偵測的 global skill，避免同一個 loader 載入重複 skill：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh
```

只有在需要同時支援 Claude Code 時，才安裝所有 adapter；Codex 與 Antigravity 仍共用同一份 `~/.agents/skills/octopulse`：

```sh
curl -fsSL https://github.com/davislinyd/OctoPulse/releases/latest/download/install.sh | sh -s -- --agent all
```

安裝器會驗證 release archive 的 SHA-256，並嘗試在 `~/.local/bin/octopulse` 建立 wrapper；此目錄通常已在 PATH。若該位置已有其他指令，安裝器不會覆寫，會改為輸出 `$OCTOPULSE_HOME/bin` 的 PATH 設定方式。再確認版本：

```sh
octopulse --version
```

## 使用方式

### 追蹤正在維護的專案

在專案的 Git root 中執行：

```sh
octopulse context
octopulse init --yes
```

`init` 會建立空的 `.otcopulse`，並將 Git root 加入使用者的受信任掃描根目錄。非瑣碎工作結束時，Agent 僅在目標、摘要、下一步、驗證或注意事項有實質變化時更新 marker，接著驗證：

```sh
octopulse validate .otcopulse
```

需要為專案加入持久化提醒時，明確指定 adapter；此動作才會以最小區塊更新 `AGENTS.md` 或 `CLAUDE.md`：

```sh
octopulse init --yes --agent codex
```

### 封存過舊專案

不再維護、但仍要出現在總覽的專案，不需要讀取原始碼或舊狀態檔：

```sh
octopulse archive --yes --reason "Superseded by the new platform."
```

這會寫入有效的 `phase: paused`、`health: stale` marker，記錄封存原因與明確的重新啟動條件。完全不需追蹤的舊專案不應建立 marker，也不應加入掃描根目錄。

### 產生跨專案報表

```sh
octopulse report --format both --explain
```

預設輸出位置是 `$OCTOPULSE_HOME/reports`；包含 `projects.json`、`latest.md` 與 `index.html`。`--explain` 會列出讀取的 marker、遺失根目錄與快取命中原因。

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
| `octopulse validate .otcopulse` | 驗證 marker schema 與大小。 |
| `octopulse root add\|list\|remove PATH` | 管理受信任的掃描根目錄。 |
| `octopulse report --format markdown\|html\|both --explain` | 產生或解釋跨專案報表。 |

## 文件語言

本檔為繁體中文主文件；[README.en.md](README.en.md) 是對應英文版本。功能、指令、範例與流程變更必須在同一個 commit 同步更新兩份 README；CLI、檔名與 schema 欄位一律維持英文。
