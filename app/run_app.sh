#!/bin/bash
# Usage: run with ./run_app.sh from directory where app.py is located
waitress-serve --port 8080 --call 'app:create_app'
