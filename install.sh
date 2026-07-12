#!/bin/sh
# Install a released OctoPulse v2 runtime and native global skill adapters.
set -eu

REPOSITORY="davislinyd/OctoPulse"
VERSION="latest"
AGENT="auto"
FORCE=0
WITHOUT_CODEX_HOOKS=0
REMOVE_CODEX_HOOKS=0

usage() {
  echo "Usage: install.sh [--version VERSION] [--agent auto|all|codex|claude|antigravity] [--force] [--without-codex-hooks|--remove-codex-hooks]" >&2
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version) VERSION="$2"; shift 2 ;;
    --agent) AGENT="$2"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --without-codex-hooks) WITHOUT_CODEX_HOOKS=1; shift ;;
    --remove-codex-hooks) REMOVE_CODEX_HOOKS=1; shift ;;
    --help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[ "$WITHOUT_CODEX_HOOKS" -eq 0 ] || [ "$REMOVE_CODEX_HOOKS" -eq 0 ] || { usage; exit 2; }

case "$AGENT" in auto|all|codex|claude|antigravity) ;; *) usage; exit 2 ;; esac
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

OCTOPULSE_HOME="${OCTOPULSE_HOME:-${XDG_CONFIG_HOME:-$HOME/.config}/octopulse}"
BASE="https://github.com/$REPOSITORY/releases"
if [ "$VERSION" = "latest" ]; then
  DOWNLOAD="$BASE/latest/download"
  RUNTIME_VERSION="latest"
else
  DOWNLOAD="$BASE/download/$VERSION"
  RUNTIME_VERSION="$VERSION"
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT HUP INT TERM
ARCHIVE="$TMPDIR/octopulse.tar.gz"
CHECKSUM="$TMPDIR/octopulse.sha256"
curl -fsSL "$DOWNLOAD/octopulse.tar.gz" -o "$ARCHIVE"
curl -fsSL "$DOWNLOAD/octopulse.sha256" -o "$CHECKSUM"
if command -v sha256sum >/dev/null 2>&1; then
  (cd "$TMPDIR" && sha256sum -c "$(basename "$CHECKSUM")")
else
  EXPECTED="$(awk '{print $1}' "$CHECKSUM")"
  ACTUAL="$(shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
  [ "$EXPECTED" = "$ACTUAL" ] || { echo "checksum verification failed" >&2; exit 1; }
fi

RUNTIME="$OCTOPULSE_HOME/runtime/$RUNTIME_VERSION"
mkdir -p "$OCTOPULSE_HOME/runtime" "$OCTOPULSE_HOME/bin"
if [ -e "$RUNTIME" ] && [ "$VERSION" != "latest" ] && [ "$FORCE" -ne 1 ]; then
  echo "$RUNTIME already exists; rerun with --force after review" >&2
  exit 1
fi
rm -rf "$RUNTIME"
mkdir -p "$RUNTIME"
tar -xzf "$ARCHIVE" -C "$RUNTIME"
cat > "$OCTOPULSE_HOME/bin/octopulse" <<EOF
#!/bin/sh
exec python3 "$RUNTIME/tools/octopulse.py" "\$@"
EOF
chmod +x "$OCTOPULSE_HOME/bin/octopulse"

CLI_COMMAND="$OCTOPULSE_HOME/bin/octopulse"
LOCAL_BIN="${XDG_BIN_HOME:-$HOME/.local/bin}"
LOCAL_COMMAND="$LOCAL_BIN/octopulse"
mkdir -p "$LOCAL_BIN"
if [ -e "$LOCAL_COMMAND" ] || [ -L "$LOCAL_COMMAND" ]; then
  if [ -L "$LOCAL_COMMAND" ] && [ "$(readlink "$LOCAL_COMMAND")" = "$CLI_COMMAND" ]; then
    :
  elif [ "$FORCE" -eq 1 ]; then
    rm -f "$LOCAL_COMMAND"
  else
    echo "$LOCAL_COMMAND already exists; leaving it unchanged" >&2
    LOCAL_COMMAND=""
  fi
fi
if [ -n "$LOCAL_COMMAND" ]; then
  ln -sfn "$CLI_COMMAND" "$LOCAL_COMMAND"
  CLI_COMMAND="$LOCAL_COMMAND"
fi

install_skill() {
  target="$1"
  parent="$(dirname "$target")"
  if [ -e "$target" ] && [ "$FORCE" -ne 1 ]; then
    if [ -f "$target/SKILL.md" ] && grep -q '^name: OctoPulse' "$target/SKILL.md"; then
      :
    else
      echo "$target already exists; not replacing it" >&2
      return
    fi
  fi
  mkdir -p "$parent"
  rm -rf "$target"
  cp -R "$RUNTIME/skills/octopulse" "$target"
  echo "installed skill: $target"
}

if [ "$AGENT" = "auto" ]; then
  if [ -d "$HOME/.agents" ]; then
    AGENT="codex"
  elif [ -d "$HOME/.claude" ]; then
    AGENT="claude"
  else
    echo "no supported Agent home found; rerun with --agent codex|claude|antigravity" >&2
    exit 1
  fi
fi

if [ "$AGENT" = "all" ] || [ "$AGENT" = "codex" ] || [ "$AGENT" = "antigravity" ]; then install_skill "$HOME/.agents/skills/octopulse"; fi
if [ "$AGENT" = "all" ] || [ "$AGENT" = "claude" ]; then install_skill "$HOME/.claude/skills/octopulse"; fi

CODEX_HOOKS_FILE="$HOME/.codex/hooks.json"
if [ "$AGENT" = "all" ] || [ "$AGENT" = "codex" ]; then
  if [ -f "$HOME/.codex/config.toml" ] && grep -qE 'octopulse_codex_hook\.py|octopulse-status' "$HOME/.codex/config.toml"; then
    echo "legacy OctoPulse hook found in ~/.codex/config.toml; disable it with Codex /hooks to avoid duplicate hooks" >&2
  fi
  if [ "$REMOVE_CODEX_HOOKS" -eq 1 ]; then
    "$CLI_COMMAND" hook codex-remove --hooks-file "$CODEX_HOOKS_FILE"
  elif [ "$WITHOUT_CODEX_HOOKS" -eq 0 ]; then
    "$CLI_COMMAND" hook codex-install --hooks-file "$CODEX_HOOKS_FILE" --command "$CLI_COMMAND"
  fi
fi

"$CLI_COMMAND" --version
case ":$PATH:" in
  *":$LOCAL_BIN:"*) echo "OctoPulse installed. Run: octopulse context" ;;
  *) echo "OctoPulse installed. Add $LOCAL_BIN or $OCTOPULSE_HOME/bin to PATH, then run: octopulse context" ;;
esac
