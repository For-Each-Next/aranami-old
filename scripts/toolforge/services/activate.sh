#!/bin/sh
# Replace Aranami's individual CronJobs with the three grouped schedules.
set -eu
umask 027
tool_dir=${ARANAMI_TOOL_DIR:-${TOOL_DATA_DIR:-/data/project/aranami}}
cd "$tool_dir"
launcher="$tool_dir/app/scripts/toolforge/run-job.sh"
state=state/toolforge-jobs
legacy='aranami-assessment-lists aranami-assessment-log aranami-dyks aranami-enwp-key-articles aranami-new-pages aranami-newsletter-daily aranami-newsletter-history aranami-pageviews aranami-pexbot aranami-quality-analysis aranami-quality-authorship aranami-website'
services='aranami-project-data aranami-data-fetch aranami-report-update'

midnight_clear() {
    case "$(date -u +%H:%M)" in
        23:59|00:00|00:01)
            printf '%s\n' 'Wait until 00:02 UTC to change schedules.' >&2
            return 1 ;;
    esac
}

record_schedules() {
    kubectl get cronjobs -o json | sh "$launcher" --record-schedules
}

midnight_clear
mkdir -p "$state" deployment-backups
mkdir deployment.lock || { printf '%s\n' 'A source or job transition is active.' >&2; exit 1; }
backup=
changed=false
finish() {
    result=$?
    trap - 0 HUP INT TERM
    if [ "$result" -ne 0 ] && [ "$changed" = true ]; then
        set +e
        rm -f "$state/grouped" "$state/active"
        if midnight_clear; then
            for name in aranami-data-fetch aranami-report-update; do
                toolforge jobs delete "$name" >/dev/null 2>&1
            done
            while IFS= read -r name; do
                toolforge jobs load --job "$name" "$backup/jobs.yaml"
            done < "$backup/previous-cronjobs"
            if [ -n "$previous" ]; then
                python3 "$tool_dir/$previous/scripts/toolforge/validate-source.py" \
                    select "$tool_dir/$previous" && toolforge jobs restart aranami-web
                record_schedules
            fi
            if [ -f "$backup/active" ]; then mv "$backup/active" "$state/active"; fi
        fi
        printf 'Job transition failed. Previous definitions and activation state: %s\n' "$backup" >&2
    fi
    rmdir deployment.lock
    exit "$result"
}
trap finish 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [ -f "$state/grouped" ]; then record_schedules; exit 0; fi
backup=$(mktemp -d "$tool_dir/deployment-backups/jobs-XXXXXXXX")
selection=$(readlink app)
token=${selection#app-staging-}
previous=$(readlink "deployment-backups/source-$token/app.before" || :)
toolforge jobs dump -f "$backup/jobs.yaml"
installed=$(kubectl get cronjobs -o custom-columns=NAME:.metadata.name --no-headers)
: > "$backup/previous-cronjobs"
for name in aranami-project-data $legacy; do
    if printf '%s\n' "$installed" | grep -Fxq "$name"; then
        printf '%s\n' "$name" >> "$backup/previous-cronjobs"
    fi
done
sh "$launcher" --manifest > "$backup/grouped.yaml"

# Pause new work and let owned child processes finish before replacing schedules.
changed=true
if [ -f "$state/active" ]; then mv "$state/active" "$backup/active"; fi
deadline=$(($(date +%s) + 900))
while :; do
    active=$(kubectl get jobs -o json)
    if ! printf '%s\n' "$active" | python3 -c '
import json
import sys
owners = set(sys.argv[1:])
items = json.load(sys.stdin)["items"]
sys.exit(any(
    item.get("status", {}).get("active", 0)
    and any(owner["name"] in owners
            for owner in item["metadata"].get("ownerReferences", []))
    for item in items
))
' aranami-project-data $legacy; then
        test "$(date +%s)" -lt "$deadline"
        sleep 10
        continue
    fi
    break
done
midnight_clear
for name in $services; do
    toolforge jobs load --job "$name" "$backup/grouped.yaml"
    kubectl get cronjob "$name" -o name
done
while IFS= read -r name; do
    if [ "$name" != aranami-project-data ]; then toolforge jobs delete "$name"; fi
done < "$backup/previous-cronjobs"
record_schedules
touch "$state/grouped"
touch "$state/active"
printf 'Grouped Aranami jobs enabled. Previous definitions: %s\n' "$backup"
