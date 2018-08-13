# boegelbot
A bot that helps out with incoming contributions to GitHub repositories of the EasyBuild project.

boegelbot will query the most recent Travis builds, and inspect the ones that failed more closely.

For each failed Travis build, it will either:

* retrigger the failed Travis jobs in case they seemed to have failed because of a fluke, or
* report back a partial log for one of the failed jobs in the corresponding pull request
