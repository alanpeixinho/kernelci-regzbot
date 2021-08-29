#!/bin/bash
#
# Runs regzbot straight from a git
#

SCRIPT=$(realpath -e ${BASH_SOURCE[0]})
SCRIPT_TOP="$(dirname ${SCRIPT})"

exec env PYTHONPATH="${SCRIPT_TOP}" python3 "${SCRIPT_TOP}/regzbot/commandl.py" "${@}"
