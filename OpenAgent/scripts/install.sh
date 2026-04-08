#!/usr/bin/env bash
# =============================================================
#  OpenAgent — 一键安装脚本 (macOS / Linux)
# =============================================================
#  用法:
#    curl -fsSL https://raw.githubusercontent.com/your-org/openagent/main/install.sh | bash
#
#  做什么:
#    1. 检测 Python 3.11+，没有则提示安装方式
#    2. pip install openagent
#    3. 验证安装成功
# =============================================================

set -euo pipefail

BOLD='\033[1m'
GREEN='\033[32m'
RED='\033[31m'
CYAN='\033[36m'
YELLOW='\033[33m'
RESET='\033[0m'

echo ""
echo -e "${BOLD}${CYAN}🤖 OpenAgent Installer${RESET}"
echo ""

# ─── Step 1: Find Python ─────────────────────────────────────
PYTHON_CMD=""

for cmd in python3 python; do
  if command -v "$cmd" &>/dev/null; then
    VERSION=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
    MAJOR=$(echo "$VERSION" | cut -d. -f1)
    MINOR=$(echo "$VERSION" | cut -d. -f2)

    if [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 11 ]; then
      PYTHON_CMD="$cmd"
      echo -e "${GREEN}✓${RESET} Found Python $VERSION ($cmd)"
      break
    fi
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  echo -e "${RED}${BOLD}✗ Python 3.11+ not found${RESET}"
  echo ""
  echo "  Please install Python 3.11+ first:"
  echo ""
  echo "    macOS:  ${CYAN}brew install python@3.12${RESET}"
  echo "    Ubuntu: ${CYAN}sudo apt update && sudo apt install python3.12${RESET}"
  echo "    Fedora: ${CYAN}sudo dnf install python3.12${RESET}"
  echo "    Arch:   ${CYAN}sudo pacman -S python${RESET}"
  echo ""
  echo "    Or download from: ${CYAN}https://www.python.org/downloads/${RESET}"
  echo ""
  echo "  Then re-run this script."
  exit 1
fi

# ─── Step 2: Ensure pip ──────────────────────────────────────
if ! "$PYTHON_CMD" -m pip --version &>/dev/null; then
  echo -e "${YELLOW}⚠${RESET}  pip not found, installing ..."
  "$PYTHON_CMD" -m ensurepip --upgrade --default-pip 2>/dev/null || {
    echo -e "${RED}✗ Failed to install pip.${RESET}"
    echo "  Try manually: ${CYAN}$PYTHON_CMD -m ensurepip --upgrade${RESET}"
    exit 1
  }
fi
echo -e "${GREEN}✓${RESET} pip available"

# ─── Step 3: Install openagent ────────────────────────────────
echo ""
echo -e "${CYAN}📦 Installing openagent ...${RESET}"
"$PYTHON_CMD" -m pip install --upgrade openagent

# ─── Step 4: Verify ──────────────────────────────────────────
echo ""
if "$PYTHON_CMD" -m openagent --help &>/dev/null; then
  echo -e "${GREEN}${BOLD}✅ OpenAgent installed successfully!${RESET}"
  echo ""
  echo "  Run:"
  echo "    ${CYAN}openagent${RESET}              # interactive REPL"
  echo "    ${CYAN}openagent chat 'hello'${RESET}  # one-shot"
  echo ""
else
  echo -e "${YELLOW}⚠  Installation completed but verification failed.${RESET}"
  echo "  Try: ${CYAN}python -m openagent${RESET}"
fi
