#!/usr/bin/env bash
# =============================================================================
# HeatShield — push this folder to GitHub in ONE command.
#
#   chmod +x push-to-github.sh && ./push-to-github.sh
#
# It asks for your repository URL, then does git init / add / commit / push.
# It also refuses to continue if .venv or node_modules would be uploaded.
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")" || exit 1

GREEN=$'\033[1;32m'; YELLOW=$'\033[1;33m'; RED=$'\033[1;31m'; OFF=$'\033[0m'

command -v git >/dev/null 2>&1 || {
  echo "${RED}git is not installed.${OFF} Install it from https://git-scm.com/downloads"
  exit 1
}

echo
echo "${GREEN}HeatShield → GitHub${OFF}"
echo
echo "  First, create an EMPTY repository at https://github.com/new"
echo "  Do NOT tick 'Add a README file', 'Add .gitignore' or 'Choose a license' —"
echo "  this project already ships all three and they would collide."
echo
printf "  Paste your repository URL (e.g. https://github.com/you/heatshield.git)\n  > "
read -r REPO

[ -z "$REPO" ] && { echo "${RED}No URL given — nothing to do.${OFF}"; exit 1; }
case "$REPO" in *.git) ;; *) REPO="${REPO%/}.git" ;; esac

[ -d .git ] || git init -q
git add -A

N=$(git ls-files | wc -l | tr -d ' ')
echo
echo "  $N files staged for commit"

if [ "$N" -gt 400 ]; then
  echo "${RED}  That is far too many files — .venv/ or node_modules/ is being included.${OFF}"
  echo "  Fix .gitignore before pushing. Aborting."
  exit 1
fi

if git ls-files | grep -qE '^(\.venv|node_modules|__pycache__)/'; then
  echo "${RED}  .venv/ or node_modules/ would be committed. Aborting.${OFF}"
  exit 1
fi

if git ls-files | grep -qx '.env'; then
  echo "${RED}  .env would be committed — it may contain Twilio keys. Aborting.${OFF}"
  exit 1
fi

git -c user.name="${GIT_USER_NAME:-HeatShield}" \
    -c user.email="${GIT_USER_EMAIL:-heatshield@example.com}" \
    commit -q -m "HeatShield: extreme heatwave early warning + human thermal stress index" \
  || echo "  (nothing new to commit — reusing the existing commit)"

git branch -M main
git remote remove origin >/dev/null 2>&1
git remote add origin "$REPO"

echo
echo "${GREEN}  Pushing to $REPO${OFF}"
echo "  (if it asks for a password, use a Personal Access Token, not your account password)"
echo
if git push -u origin main; then
  SLUG=$(echo "$REPO" | sed -E 's#.*github\.com[:/]([^/]+)/([^/]+)\.git#\1/\2#')
  echo
  echo "${GREEN}  Done → https://github.com/$SLUG${OFF}"
  echo "  Check the Actions tab: the CI workflow should go green within a minute."
  exit 0
fi

# --- push rejected: the remote already has a commit -------------------------
echo
echo "${YELLOW}  Push was rejected — the remote already has a commit.${OFF}"
echo "  (A half-finished browser upload lands here: it uploads the files at the"
echo "   top level and silently drops every nested folder, so GitHub shows ~22"
echo "   files and no source code at all.)"
echo
printf "  Replace the remote contents with this complete project? [y/N] "
read -r YN
case "$YN" in
  [yY]*)
    echo
    echo "  Force-pushing..."
    if git push -u origin main --force; then
      SLUG=$(echo "$REPO" | sed -E 's#.*github\.com[:/]([^/]+)/([^/]+)\.git#\1/\2#')
      echo
      echo "${GREEN}  Done → https://github.com/$SLUG${OFF}"
      echo "  Verify: the repo home page must show ~110 files, and core/, app/,"
      echo "  scripts/, tests/, data/ and frontend/ must all be visible."
    else
      echo "${RED}  Still failed.${OFF} Check the URL, and use a Personal Access Token"
      echo "  (not your account password) when prompted."
    fi
    ;;
  *)
    echo "  Nothing pushed. Create a fresh EMPTY repo at github.com/new and re-run this script."
    ;;
esac
