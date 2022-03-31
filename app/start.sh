#!bin/bash
# shellcheck disable=SC2239
. venv/bin/activate
export ENV=dev
# export DATA_MIGRATION=true
uvicorn main:app --host 0.0.0.0 --port 8100 --reload  --reload-exclude=helper/**