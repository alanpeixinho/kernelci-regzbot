#!/bin/bash
#
# Runs regzbot straight from a git
#

SCRIPT=$(realpath -e ${BASH_SOURCE[0]})
SCRIPT_TOP="$(dirname ${SCRIPT})"

VENV="$HOME/.local/share/regzbot/python-venv"

[ -d ${VENV} ] && source ${VENV}/bin/activate

if [[ -e "$(dirname "${0}")/regzbot/${1}" ]]; then
    toexecute="${1}"
    shift
    exec env PYTHONPATH="${SCRIPT_TOP}" python3 "${SCRIPT_TOP}/regzbot/${toexecute}" "${@}"
else
    exec env PYTHONPATH="${SCRIPT_TOP}" python3 "${SCRIPT_TOP}/regzbot/commandl.py" "${@}"
fi
