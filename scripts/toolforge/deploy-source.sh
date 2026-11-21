#!/bin/sh
# Validate immutable code, select it atomically, and roll out the web service.
set -eu
umask 027
tool_dir=${ARANAMI_TOOL_DIR:-/data/project/aranami}
case "$tool_dir" in
    ''|/|*[!A-Za-z0-9_./-]*) printf '%s\n' 'Expected a canonical tool directory.' >&2; exit 2 ;;
esac
test -d "$tool_dir" && test ! -L "$tool_dir"
# Toolforge's /data/project mount has a different physical path on the bastion.
# Keep the portable mount name, but reject non-normalized caller paths.
test "$(CDPATH='' cd -L "$tool_dir" && pwd -L)" = "$tool_dir"
stage=${1-}
token=${stage#"$tool_dir/app-staging-"}
case "$token" in
    ''|*[!a-f0-9]*) printf '%s\n' 'Supply the exact uploaded staging directory.' >&2; exit 2 ;;
esac
test "${#token}" -eq 32
test "$stage" = "$tool_dir/app-staging-$token"
validator="$stage/scripts/toolforge/validate-source.py"
# No jobs, source directories, or runtime data change before this succeeds.
python3 "$validator" verify "$stage"
cd "$tool_dir"
# The completed layout conversion belongs to retained v0.9.8 recovery tooling.
# Reject old runtime owners before setup instead of silently ignoring their facts.
for obsolete in reports/data reports/records cache/toolforge \
    data/daily data/hourly data/imports data/conversion data/wikitext \
    data/.wikitext-locks data/.page-staging; do
    if [ -e "$obsolete" ] || [ -L "$obsolete" ]; then
        printf 'Retire verified legacy data before deployment: %s\n' "$obsolete" >&2
        exit 1
    fi
done
for path in deployment-backups deployment-envs; do
    test ! -L "$path"
    if [ -e "$path" ]; then test -d "$path"; fi
done
if [ -L app ]; then
    previous_source=$(readlink app)
    previous_token=${previous_source#app-staging-}
    case "$previous_token" in ''|*[!a-f0-9]*) exit 2 ;; esac
    test "${#previous_token}" -eq 32 && test "$previous_source" = "app-staging-$previous_token"
    python3 "$tool_dir/$previous_source/scripts/toolforge/validate-source.py" runtime "$tool_dir/$previous_source" >/dev/null
elif [ -e app ]; then
    printf '%s\n' 'Expected app to select an immutable generation.' >&2
    exit 2
fi
mkdir deployment.lock || { printf '%s\n' 'Another deployment holds deployment.lock.' >&2; exit 1; }
backup=
setup_started=false
selected=false

wait_stopped() {
    selector=$1
    remaining=$(kubectl get pods -l "$selector" -o name) || return 1
    if [ -n "$remaining" ]; then
        kubectl wait --for=delete pod -l "$selector" --timeout=180s || return 1
    fi
    remaining=$(kubectl get pods -l "$selector" -o name) || return 1
    test -z "$remaining"
}

finish() {
    status=$?
    trap - 0 HUP INT TERM
    set +e
    release_lock=true
    if [ -L app ] && [ "$(readlink app)" = "${stage##*/}" ]; then selected=true; fi
    if [ "$status" -ne 0 ]; then
        if [ "$setup_started" = true ]; then
            toolforge jobs delete "$setup_job" >/dev/null 2>&1
            if ! wait_stopped "app.kubernetes.io/name=$setup_job"; then
                release_lock=false
                printf '%s\n' 'Setup shutdown is unconfirmed; deployment.lock retained for inspection.' >&2
            fi
        fi
        if [ "$selected" = false ]; then
            printf 'Deployment failed before activation; prior source retained. Inspect service state and backup: %s\n' "$backup" >&2
        else
            printf 'Code activated, but the web rollout failed. Retained both generations; inspect jobs before retrying. Backup: %s\n' "$backup" >&2
        fi
    fi
    if [ "$release_lock" = true ]; then rmdir deployment.lock; fi
    exit "$status"
}
trap finish 0
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p deployment-backups deployment-envs
backup="$tool_dir/deployment-backups/source-$token"
# A token is used once; never overwrite another transaction's setup proof.
mkdir "$backup"
environment="$tool_dir/deployment-envs/source-$token"
receipt="$backup/setup-success.json"
setup_job="aranami-setup-$token"
if [ -L app ]; then cp -P app "$backup/app.before"; fi
# Dependency installation never mutates the active environment or source.
setup_started=true
toolforge jobs run "$setup_job" --image python3.13 --no-filelog --mount=all \
    --command "env ARANAMI_TOOL_DIR=$tool_dir sh $stage/scripts/toolforge/setup-env.sh $stage $receipt $environment" --wait 1800
# --wait is not evidence of a successful container exit: require exact proof.
python3 "$validator" receipt "$stage" "$receipt"
setup_started=false
# Observe the current jobs after setup, which may take several minutes.
toolforge jobs dump -f "$backup/jobs.yaml"
if [ -f state/toolforge-jobs/active ]; then
    kubectl get cronjobs -o json |
        PYTHONPATH="$stage/src" "$environment/bin/python" -B -m runtime.services --record-schedules
fi
replicas=$(kubectl get deployment aranami-web --ignore-not-found -o 'jsonpath={.spec.replicas}')
case "$replicas" in
    *[!0-9]*) printf '%s\n' 'Invalid replica count for aranami-web.' >&2; exit 1 ;;
esac
# app is the only selection pointer. Keep every uploaded source at its path.
python3 "$validator" select "$stage"
selected=true
if [ -n "$replicas" ] && [ "$replicas" != 0 ]; then
    printf '%s\n' "$replicas" > "$backup/aranami-web.replicas"
    current=$(kubectl get deployment aranami-web --ignore-not-found -o 'jsonpath={.spec.replicas}')
    test "$current" = "$replicas" || {
        printf '%s\n' 'Web replica count changed during deployment.' >&2; exit 1;
    }
    old_pods=$(kubectl get pods -l 'app.kubernetes.io/name=aranami-web' -o name)
    toolforge jobs restart aranami-web
    if [ -n "$old_pods" ]; then
        # Kubernetes supplies whitespace-separated resource names here.
        kubectl wait --for=delete $old_pods --timeout=180s
    fi
    kubectl rollout status deployment/aranami-web --timeout=180s
fi
printf '%s\n' 'Validated source activated.' \
    "Backup directory $backup" \
    "Generate grouped job definitions with sh $tool_dir/app/scripts/toolforge/run-job.sh --manifest"
