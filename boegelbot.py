#!/usr/bin/env python
"""
A bot that helps out with incoming contributions to the EasyBuild project

author: Kenneth Hoste (kenneth.hoste@ugent.be)
"""
import os
import re
import travispy

from easybuild.tools.github import fetch_github_token 


TRAVIS_URL = 'https://travis-ci.org'
VERSION = '20180813.01'


def is_travis_fluke(job_log_txt):
    """Detect fluke failures in Travis job log."""
    fluke_patterns = [
        r"Failed to connect to .* port [0-9]+: Connection timed out",
        r"fatal: unable to access .*: Failed to connect to github.com port [0-9]+: Connection timed out",
        r"Could not connect to ppa.launchpad.net.*, connection timed out",
        r"Failed to fetch .* Unable to connect to ppa.launchpad.net:http",
        r"ERROR 504: Gateway Time-out",
        r"Could not connect to .*, connection timed out",
        r"No output has been received in the last [0-9]*m[0-9]*s, this potentially indicates a stalled build",
        r"curl.*SSL read: error",
        r"A TLS packet with unexpected length was received",
        r"ReadTimeoutError:.*Read timed out",
    ]
    fluke = False
    for pattern in fluke_patterns:
        regex = re.compile(pattern, re.M)
        if regex.search(job_log_txt):
            fluke = True
            break

    return fluke


def fetch_travis_failed_builds(github_account, repository, owner, github_token):
    """Scan Travis test runs for failures, and return notification to be sent to PR if one is found"""
    travis = travispy.TravisPy.github_auth(github_token)

    repo_slug = '%s/%s' % (github_account, repository)
    last_builds = travis.builds(slug=repo_slug, event_type='pull_request')

    done_prs = []

    res = []
    for build in last_builds:
        bid, pr = build.number, build.pull_request_number

        if pr in done_prs:
            print "(skipping test suite run for already processed PR #%s)" % pr
            continue

        done_prs.append(pr)

        if build.successful:
            print "(skipping successful test suite run %s for PR %s)" % (bid, pr)

        else:
            build_url = os.path.join(TRAVIS_URL, repo_slug, 'builds', str(build.id))
            print "[id: %s] PR #%s - %s - %s" % (bid, pr, build.state, build_url)

            jobs = [(str(job_id), travis.jobs(ids=[job_id])[0]) for job_id in sorted(build.job_ids)]
            jobs_ok = [job.successful for (_, job) in jobs]

            pr_comment = "Travis test report: %d/%d runs failed - " % (jobs_ok.count(False), len(jobs))
            pr_comment += "see %s\n" % build_url
            check_msg = pr_comment.strip()

            jobs = [(job_id, job) for (job_id, job) in jobs if job.unsuccessful]
            if jobs:

                # detect fluke failures in jobs, and restart them
                flukes = []
                for (job_id, job) in jobs:
                    if is_travis_fluke(job.log.body):
                        flukes.append(job_id)

                if flukes:
                    boegel_gh_token = fetch_github_token('boegel')
                    if boegel_gh_token:
                        travis_boegel = travispy.TravisPy.github_auth(boegel_gh_token)
                        for (job_id, job) in zip(flukes, travis_boegel.jobs(ids=flukes)):
                            print "[id %s] PR #%s - fluke detected in job ID %s, restarting it!" % (bid, pr, job_id)
                            if job.restart():
                                print "Job ID %s restarted" % job_id
                            else:
                                print "Failed to restart job ID %s!" % job_id

                        # filter out fluke jobs, we shouldn't report these
                        jobs = [(job_id, job) for (job_id, job) in jobs if job_id not in flukes]
                    else:
                        print "Can't restart Travis jobs that failed due to flukes, no GitHub token found"

                if jobs:
                    job_url = os.path.join(TRAVIS_URL, repo_slug, 'jobs', jobs[0][0])
                    pr_comment += "\nOnly showing partial log for 1st failed test suite run %s;\n" % jobs[0][1].number
                    pr_comment += "full log at %s\n" % job_url

                    # try to filter log to just the stuff that matters
                    retained_log_lines = jobs[0][1].log.body.split('\n')
                    for idx, log_line in enumerate(retained_log_lines):
                        if repository == 'easybuild-easyconfigs':
                            if log_line.startswith('FAIL:') or log_line.startswith('ERROR:'):
                                retained_log_lines = retained_log_lines[idx:]
                                break
                        elif log_line.strip().endswith("$ python -O -m test.%s.suite" % repository.split('-')[-1]):
                            retained_log_lines = retained_log_lines[idx:]
                            break

                    pr_comment += '```\n...\n'
                    pr_comment += '\n'.join(retained_log_lines[-100:])
                    pr_comment += '\n```\n'

                    for (job_id, job) in jobs[1:]:
                        job_url = os.path.join(TRAVIS_URL, repo_slug, 'jobs', job_id)
                        pr_comment += "* %s - %s => %s\n" % (job.number, job.state, job_url)

                    pr_comment += "\n*bleep, bloop, I'm just a bot (boegelbot v%s)*" % VERSION
                    pr_comment += "Please talk to my owner @%s if you notice you me acting stupid)," % owner
                    pr_comment += "or submit a pull request to https://github.com/boegel/boegelbot fix the problem."

                    res.append((pr, pr_comment, check_msg))

                else:
                    print "(no more failed jobs after filtering out flukes for id %s PR #%s)" % (bid, pr)

    print "Processed %d builds, found %d PRs with failed builds to report back on" % (len(last_builds), len(res))

    return res


github_user = 'boegel'
github_token = fetch_github_token(github_user)
fetch_travis_failed_builds('easybuilders', 'easybuild-easyconfigs', github_user, github_token)
