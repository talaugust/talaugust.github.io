#!/usr/bin/env bash
# Serve the site locally so you can preview changes before pushing.
#
# Usage:
#   bin/serve_local.sh           # auto: uses local bundle if available, else docker
#   bin/serve_local.sh local     # force local bundler
#   bin/serve_local.sh docker    # force docker-compose
#
# Then open http://localhost:8080 (docker) or http://localhost:4000 (local).
# The news items you want to eyeball live on the home page.

set -euo pipefail

cd "$(dirname "$0")/.."

mode="${1:-auto}"

run_local() {
  echo ">> serving with local bundler on http://localhost:4000"
  bundle check >/dev/null 2>&1 || bundle install
  exec bundle exec jekyll serve --lsi --livereload --incremental
}

run_docker() {
  echo ">> serving with docker on http://localhost:8080"
  rm -f Gemfile.lock
  exec docker-compose up
}

case "$mode" in
  local)  run_local ;;
  docker) run_docker ;;
  auto)
    if command -v bundle >/dev/null 2>&1; then
      run_local
    elif command -v docker-compose >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
      run_docker
    else
      echo "error: neither bundle nor docker found on PATH" >&2
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [auto|local|docker]" >&2
    exit 2
    ;;
esac
