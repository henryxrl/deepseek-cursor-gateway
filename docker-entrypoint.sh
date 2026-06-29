#!/bin/bash
# docker-entrypoint.sh — translate environment variables into CLI flags
set -euo pipefail

# Helper: append "--flag value" directly to args array (safe for values with spaces)
add_flag_val() {
    local var_name="$1" flag="$2"
    local val="${!var_name:-}"
    if [ -n "${val}" ]; then
        args+=("${flag}" "${val}")
    fi
}

# Helper: append "--flag" or "--no-flag" directly to args array
add_flag_bool() {
    local var_name="$1" flag="$2"
    local val="${!var_name:-}"
    case "${val}" in
        1|true|True|TRUE|yes|Yes|YES|on|On|ON)
            args+=("${flag}") ;;
        0|false|False|FALSE|no|No|NO|off|Off|OFF)
            args+=("--no-${flag#--}") ;;
    esac
}

# Build the argument array
args=()

# These two always make sense for Docker
args+=(--host "${GATEWAY_HOST:-0.0.0.0}")
args+=(--config "${GATEWAY_CONFIG:-/data/config.yaml}")

# Parse booleans
case "${GATEWAY_NGROK:-0}" in
    1|true|True|TRUE|yes|Yes|YES|on|On|ON)
        args+=(--ngrok) ;;
    *)
        args+=(--no-ngrok) ;;
esac
add_flag_bool GATEWAY_VERBOSE         --verbose
add_flag_bool GATEWAY_DISPLAY_REASONING --display-reasoning
add_flag_bool GATEWAY_COLLAPSIBLE_REASONING --collapsible-reasoning
add_flag_bool GATEWAY_CORS            --cors

# Parse valued flags
add_flag_val GATEWAY_PORT                    --port
add_flag_val GATEWAY_MODEL                   --model
add_flag_val GATEWAY_BASE_URL                --base-url
add_flag_val GATEWAY_THINKING                --thinking
add_flag_val GATEWAY_REASONING_EFFORT        --reasoning-effort
add_flag_val GATEWAY_REASONING_CONTENT_PATH  --reasoning-content-path
add_flag_val GATEWAY_NGROK_URL               --ngrok-url
add_flag_val GATEWAY_TRACE_DIR               --trace-dir
add_flag_val GATEWAY_REQUEST_TIMEOUT         --request-timeout
add_flag_val GATEWAY_MAX_REQUEST_BODY_BYTES  --max-request-body-bytes
add_flag_val GATEWAY_REASONING_CACHE_MAX_AGE_SECONDS --reasoning-cache-max-age-seconds
add_flag_val GATEWAY_REASONING_CACHE_MAX_ROWS --reasoning-cache-max-rows
add_flag_val GATEWAY_MISSING_REASONING_STRATEGY --missing-reasoning-strategy
add_flag_val GATEWAY_USER_MESSAGE_SUFFIX     --user-suffix
add_flag_val GATEWAY_UPSTREAM_MAX_INFLIGHT   --upstream-max-inflight
add_flag_val GATEWAY_UPSTREAM_QUEUE_TIMEOUT_SECONDS --upstream-queue-timeout-seconds
add_flag_val GATEWAY_UPSTREAM_RETRY_MAX_ATTEMPTS --upstream-retry-max-attempts
add_flag_val GATEWAY_UPSTREAM_RETRY_BASE_DELAY_SECONDS --upstream-retry-base-delay-seconds
add_flag_val GATEWAY_UPSTREAM_RETRY_MAX_DELAY_SECONDS --upstream-retry-max-delay-seconds
add_flag_val GATEWAY_UPSTREAM_RETRY_JITTER_SECONDS --upstream-retry-jitter-seconds
add_flag_bool GATEWAY_UPSTREAM_RETRY_ENABLED --upstream-retry
add_flag_bool GATEWAY_UPSTREAM_RESPECT_RETRY_AFTER --upstream-respect-retry-after
add_flag_bool GATEWAY_UPSTREAM_COOLDOWN_ON_429 --upstream-cooldown-on-429
add_flag_bool GATEWAY_REQUEST_START_RATE_LIMIT_ENABLED --request-start-rate-limit
add_flag_val GATEWAY_REQUEST_START_RATE_PER_MINUTE --request-start-rate-per-minute
add_flag_val GATEWAY_REQUEST_START_BURST --request-start-burst
add_flag_val GATEWAY_IMAGE_HANDLING --image-handling
add_flag_val GATEWAY_VISION_BACKEND --vision-backend
add_flag_val GATEWAY_VISION_BASE_URL --vision-base-url
add_flag_val GATEWAY_VISION_MODEL --vision-model
add_flag_val GATEWAY_VISION_API_KEY --vision-api-key
add_flag_val GATEWAY_VISION_TIMEOUT --vision-timeout
add_flag_val GATEWAY_VISION_CONCURRENCY --vision-concurrency
add_flag_val GATEWAY_VISION_WARMUP --vision-warmup
add_flag_val GATEWAY_VISION_FALLBACK_BACKEND --vision-fallback-backend
add_flag_val GATEWAY_TESSERACT_LANG --tesseract-lang

exec deepseek-cursor-gateway "${args[@]}" "$@"
