#!/usr/bin/env bash
# kamilya-target: vm126
# kamilya-mode: read-only
# kamilya-correlation: none
# kamilya-output: sanitized
set -Eeuo pipefail
sudo -n docker inspect --format 'EVIDENCE|container={{.Name}}|image={{.Config.Image}}|status={{.State.Status}}|restarts={{.RestartCount}}' kamilya-dev-worker
