#!/bin/sh
set -e
locust --host="http://${FRONTEND_ADDR}" --headless -u "${USERS:-10}"