#!/bin/sh
set -eu
: "${PAIR_AKI_AGH_UPSTREAM:?Set an absolute directory outside this repository for the pinned upstream source}"
PIN=4bc36bc4c4441206388a53bece17379c1d7be14d
if [ -e "$PAIR_AKI_AGH_UPSTREAM" ]; then
  echo 'Use a new upstream directory; existing checkouts are preserved.' >&2
  exit 1
fi
git init "$PAIR_AKI_AGH_UPSTREAM"
git -C "$PAIR_AKI_AGH_UPSTREAM" remote add origin https://github.com/AgnesAI-Labs/agnes-harness.git
git -C "$PAIR_AKI_AGH_UPSTREAM" fetch --depth 1 --filter=blob:none origin "$PIN"
git -C "$PAIR_AKI_AGH_UPSTREAM" sparse-checkout set packages/core/src packages/protocol/src packages/protocol/gen/ts packages/protocol-validation/src packages/extension-api/src packages/resource-control-contracts/src
git -C "$PAIR_AKI_AGH_UPSTREAM" checkout --detach FETCH_HEAD
cp "$(dirname "$0")/upstream-manifest.json" "$PAIR_AKI_AGH_UPSTREAM/source-manifest.json"
