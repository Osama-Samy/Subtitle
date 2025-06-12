#!/bin/bash
pip install --upgrade pip
pip install -r requirements.txt
gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
