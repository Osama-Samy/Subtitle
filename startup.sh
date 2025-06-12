#!/bin/bash
echo "Running startup.sh script"
gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
