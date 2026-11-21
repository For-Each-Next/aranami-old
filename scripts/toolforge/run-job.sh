#!/bin/sh
# Run a single collection or report from one validated source generation.
set -eu
umask 077
tool_dir=${ARANAMI_TOOL_DIR:-${TOOL_DATA_DIR:-/data/project/aranami}}
. "$tool_dir/app/scripts/toolforge/runtime-env.sh"
export ARANAMI_TOOL_DIR="$tool_dir" PYWIKIBOT_DIR="$tool_dir"
exec "$runtime_python" -m runtime.toolforge_job "$@"
