# boegelbot
A bot that helps out with incoming contributions to GitHub repositories of the EasyBuild project.

boegelbot will query the most recent GitHub Actions workflows, and inspect the ones that failed more closely.

For each failed test run on GitHub Actions, it will either:

* retrigger the GitHub Actions workflow in case they seemed to have failed because of a fluke, or
* report back a partial log for one of the failed jobs in the corresponding pull request
