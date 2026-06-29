#!/bin/bash
# tests/test_entrypoint.sh — verify docker-entrypoint.sh helper functions preserve argument integrity
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENTRYPOINT="$SCRIPT_DIR/../docker-entrypoint.sh"

# Extract the helper function definitions without executing the script
eval "$(sed -n '/^add_flag_val()/,/^}/p' "$ENTRYPOINT")"
eval "$(sed -n '/^add_flag_bool()/,/^}/p' "$ENTRYPOINT")"

pass=0
fail=0

assert_eq() {
    local label="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        pass=$((pass + 1))
    else
        fail=$((fail + 1))
        echo "FAIL: $label"
        echo "  expected: '$expected'"
        echo "  actual:   '$actual'"
    fi
}

assert_args() {
    local label="$1"
    shift
    local expected=("$@")

    if [ "${#args[@]}" -ne "${#expected[@]}" ]; then
        fail=$((fail + 1))
        echo "FAIL: $label"
        echo "  expected count: ${#expected[@]}"
        echo "  actual count:   ${#args[@]}"
        echo "  actual args:    ${args[*]:-}"
        return
    fi

    local i
    for ((i = 0; i < ${#expected[@]}; i++)); do
        if [ "${args[$i]}" != "${expected[$i]}" ]; then
            fail=$((fail + 1))
            echo "FAIL: $label"
            echo "  at index: $i"
            echo "  expected: '${expected[$i]}'"
            echo "  actual:   '${args[$i]}'"
            return
        fi
    done

    pass=$((pass + 1))
}

# --- add_flag_val tests ---

# Value with spaces stays as single argument
export GATEWAY_TEST_SPACES="Please answer in Chinese"
args=()
add_flag_val GATEWAY_TEST_SPACES --test-flag
assert_args "spaces preserved" --test-flag "Please answer in Chinese"

# Simple value
export GATEWAY_TEST_SIMPLE="hello"
args=()
add_flag_val GATEWAY_TEST_SIMPLE --greeting
assert_args "simple value" --greeting hello

# URL with query params
export GATEWAY_TEST_URL="https://api.example.com/v1?key=val"
args=()
add_flag_val GATEWAY_TEST_URL --base-url
assert_args "url preserved" --base-url "https://api.example.com/v1?key=val"

# Unset env var adds nothing
unset GATEWAY_TEST_MISSING
args=()
add_flag_val GATEWAY_TEST_MISSING --missing
assert_args "unset var"

# Empty env var adds nothing
export GATEWAY_TEST_EMPTY=""
args=()
add_flag_val GATEWAY_TEST_EMPTY --empty
assert_args "empty var"

# --- add_flag_bool tests ---

# true values
for val in 1 true True TRUE yes Yes YES on On ON; do
    export GATEWAY_TEST_BOOL="$val"
    args=()
    add_flag_bool GATEWAY_TEST_BOOL --enable
    assert_args "bool true ($val)" --enable
done

# false values
for val in 0 false False FALSE no No NO off Off OFF; do
    export GATEWAY_TEST_BOOL="$val"
    args=()
    add_flag_bool GATEWAY_TEST_BOOL --enable
    assert_args "bool false ($val)" --no-enable
done

# Unset bool adds nothing
unset GATEWAY_TEST_BOOL_UNSET
args=()
add_flag_bool GATEWAY_TEST_BOOL_UNSET --debug
assert_args "bool unset"

# --- full entrypoint mapping tests ---

args=()
while IFS= read -r line; do
    args+=("$line")
done < <(
    env -i PATH="$PATH" \
        GATEWAY_UPSTREAM_MAX_INFLIGHT=7 \
        GATEWAY_UPSTREAM_QUEUE_TIMEOUT_SECONDS=12.5 \
        GATEWAY_UPSTREAM_RETRY_ENABLED=false \
        GATEWAY_UPSTREAM_RETRY_MAX_ATTEMPTS=4 \
        GATEWAY_UPSTREAM_RETRY_BASE_DELAY_SECONDS=1.5 \
        GATEWAY_UPSTREAM_RETRY_MAX_DELAY_SECONDS=20 \
        GATEWAY_UPSTREAM_RETRY_JITTER_SECONDS=0.25 \
        GATEWAY_UPSTREAM_RESPECT_RETRY_AFTER=no \
        GATEWAY_UPSTREAM_COOLDOWN_ON_429=on \
        GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED=yes \
        GATEWAY_REQUEST_START_RATE_PER_MINUTE=30 \
        GATEWAY_REQUEST_START_BURST=3 \
        GATEWAY_IMAGE_HANDLING=reject \
        GATEWAY_VISION_BACKEND=gemini \
        GATEWAY_VISION_BASE_URL="https://vision.example.com/v1?tenant=a b" \
        GATEWAY_VISION_MODEL="gemini-2.0-flash" \
        GATEWAY_VISION_API_KEY="sk vision key" \
        GATEWAY_VISION_TIMEOUT=42 \
        GATEWAY_VISION_CONCURRENCY=3 \
        GATEWAY_VISION_WARMUP=require \
        GATEWAY_VISION_FALLBACK_BACKEND=tesseract \
        GATEWAY_TESSERACT_LANG="eng+chi_sim" \
        bash -c 'exec(){ printf "%s\n" "$@"; }; entrypoint="$1"; shift; source "$entrypoint"' _ "$ENTRYPOINT"
)
assert_args "entrypoint maps upstream traffic env vars" \
    deepseek-cursor-gateway \
    --host 0.0.0.0 \
    --config /data/config.yaml \
    --no-ngrok \
    --upstream-max-inflight 7 \
    --upstream-queue-timeout-seconds 12.5 \
    --upstream-retry-max-attempts 4 \
    --upstream-retry-base-delay-seconds 1.5 \
    --upstream-retry-max-delay-seconds 20 \
    --upstream-retry-jitter-seconds 0.25 \
    --no-upstream-retry \
    --no-upstream-respect-retry-after \
    --upstream-cooldown-on-429 \
    --request-start-rate-limit \
    --request-start-rate-per-minute 30 \
    --request-start-burst 3 \
    --image-handling reject \
    --vision-backend gemini \
    --vision-base-url "https://vision.example.com/v1?tenant=a b" \
    --vision-model gemini-2.0-flash \
    --vision-api-key "sk vision key" \
    --vision-timeout 42 \
    --vision-concurrency 3 \
    --vision-warmup require \
    --vision-fallback-backend tesseract \
    --tesseract-lang "eng+chi_sim"

args=()
while IFS= read -r line; do
    args+=("$line")
done < <(
    env -i PATH="$PATH" \
        bash -c 'exec(){ printf "%s\n" "$@"; }; entrypoint="$1"; shift; source "$entrypoint" --help' _ "$ENTRYPOINT"
)
assert_args "entrypoint disables ngrok by default and forwards command args" \
    deepseek-cursor-gateway \
    --host 0.0.0.0 \
    --config /data/config.yaml \
    --no-ngrok \
    --help

# --- Summary ---
echo ""
echo "$pass passed, $fail failed"

[ "$fail" -eq 0 ] || exit 1
