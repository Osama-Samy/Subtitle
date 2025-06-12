#!/bin/bash

echo "Activating virtual environment..."
source antenv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing requirements..."
pip install -r requirements.txt

echo "Starting app with gunicorn..."
gunicorn -w 1 -k uvicorn.workers.UvicornWorker main:app
