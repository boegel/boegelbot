GitHub App implemented in `app.py`

* only tested with Python 3
* requires:
  * Flask (`pip install flask`)
    * Flask tutorial: https://flask.palletsprojects.com/en/1.1.x/tutorial/
  * PyGitHub (`pip install PyGithub`)
    * https://github.com/PyGithub/PyGithub
    * API: https://pygithub.readthedocs.io/en/latest/reference.html
* script to start app: `run_app.sh`

#### References

* example GitHub App implemented in Python: https://github.com/OrkoHunter/pep8speaks/blob/master/server.py

* production set up Flask app with waitress: https://flask.palletsprojects.com/en/1.1.x/tutorial/deploy/
  ```
  ./run_app.sh
  ```

* reflex to automatically rerun web app when code changes: https://github.com/cespare/reflex
  ```
  ~/go/bin/reflex -s -r 'app.py' -- ./run_app.sh
  ```
  (install with `go get github.com/cespare/reflex`)

* ngrok tunnel: https://dashboard.ngrok.com
  ```
  ~/ngrok http 8080
  ```
  (download as static binary)
