#!/bin/bash
# Usage: run with ./run_app.sh from directory where app.py is located
waitress-serve --port 3000 --call 'app:main'
