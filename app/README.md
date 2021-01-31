GitHub App implemented in `app.py`

* only tested with Python 3
* requires:
  * Flask (`pip install flask`)
    * Flask tutorial: https://flask.palletsprojects.com/en/1.1.x/tutorial/
  * PyGitHub (`pip install PyGithub`)
    * https://github.com/PyGithub/PyGithub
    * API: https://pygithub.readthedocs.io/en/latest/reference.html
  * Waitress (`pip install Waitress`)
    * https://docs.pylonsproject.org/projects/waitress/en/stable/
* script to start app: `run_app.sh`

#### Setup

Two environment variables must be set:

* `$GITHUB_APP_SECRET_TOKEN` (see https://github.com/settings/apps/boegelbotapp)

* `$GITHUB_TOKEN`: Personal Access Token (PAT) for account to use to create comments, etc.

#### References

* example GitHub App implemented in Python: https://github.com/OrkoHunter/pep8speaks/blob/master/server.py

* production set up Flask app with waitress: https://flask.palletsprojects.com/en/1.1.x/tutorial/deploy/
  ```
  ./run_app.sh
  ```

* smee.io for sending GitHub webhooks to app,
  see https://docs.github.com/en/developers/apps/setting-up-your-development-environment-to-create-a-github-app#step-1-start-a-new-smee-channel
  ```
  smee -u <smee.io URL>
  ```

* reflex to automatically rerun web app when code changes: https://github.com/cespare/reflex
  ```
  ~/go/bin/reflex -s -r 'app.py' -- ./run_app.sh
  ```
  (install with `go get github.com/cespare/reflex`)
