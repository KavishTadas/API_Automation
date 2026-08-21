#!/usr/bin/env bash
set -euo pipefail

if ! command -v postman >/dev/null 2>&1; then
  echo "Error: Postman CLI not installed. Run: npm install -g postman"
  exit 1
fi

if [[ -z "${POSTMAN_API_KEY:-}" ]]; then
  echo "Error: POSTMAN_API_KEY environment variable is not set."
  exit 1
fi

ENVIRONMENT="uat"
COLLECTION="all"
BAIL=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      ENVIRONMENT="${2:-}"
      shift 2
      ;;
    --collection)
      COLLECTION="${2:-}"
      shift 2
      ;;
    --bail)
      BAIL=true
      shift
      ;;
    *)
      echo "Error: Unknown argument: $1"
      exit 1
      ;;
  esac
done

case "$ENVIRONMENT" in
  uat)
    ENV_UID="${POSTMAN_UAT_ENV_UID:-uat}"
    ;;
  local)
    ENV_UID="${POSTMAN_LOCAL_ENV_UID:-local}"
    ;;
  *)
    echo "Error: --env must be one of: uat, local"
    exit 1
    ;;
esac

run_collection() {
  local collection_uid="$1"
  local command=(postman collection run "$collection_uid" -e "$ENV_UID" --api-key "$POSTMAN_API_KEY")

  if [[ "$BAIL" == true ]]; then
    command+=(--bail)
  fi

  "${command[@]}"
}

STATUS=0

if [[ "$COLLECTION" == "all" ]]; then
  while IFS= read -r collection_uid || [[ -n "$collection_uid" ]]; do
    collection_uid="${collection_uid%%#*}"
    collection_uid="${collection_uid#"${collection_uid%%[![:space:]]*}"}"
    collection_uid="${collection_uid%"${collection_uid##*[![:space:]]}"}"

    if [[ -z "$collection_uid" ]]; then
      continue
    fi

    if ! run_collection "$collection_uid"; then
      STATUS=1
      if [[ "$BAIL" == true ]]; then
        break
      fi
    fi
  done < scripts/collections.conf
else
  if ! run_collection "$COLLECTION"; then
    STATUS=1
  fi
fi

if [[ "$STATUS" -eq 0 ]]; then
  echo "PASS"
  exit 0
fi

echo "FAIL"
exit 1
