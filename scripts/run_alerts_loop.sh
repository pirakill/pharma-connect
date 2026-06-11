#!/bin/sh
# Align to hour boundary, then run scheduled SMS alerts each hour.
set -e
sleep $((3600 - $(date +%M) * 60 - $(date +%S)))
while true; do
  flask run-alerts
  sleep 3600
done