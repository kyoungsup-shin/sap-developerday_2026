#!/usr/bin/env bash

# Push the selected branch to SAP GitHub and the public GitHub repository.
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel)
cd "$repo_root"

branch=${1:-$(git branch --show-current)}
if [[ -z "$branch" ]]; then
  echo "No branch is checked out. Pass a branch name explicitly." >&2
  exit 1
fi

sap_remote=${SAP_GITHUB_REMOTE:-sap}
public_remote=${PUBLIC_GITHUB_REMOTE:-https://github.com/kyoungsup-shin/sap-developerday_2026.git}

echo "Pushing $branch to SAP GitHub ($sap_remote)..."
git push "$sap_remote" "$branch"

echo "Pushing $branch to public GitHub ($public_remote)..."
git push "$public_remote" "$branch"
