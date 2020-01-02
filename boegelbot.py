#!/usr/bin/env python
"""
A bot that helps out with incoming contributions to the EasyBuild project

author: Kenneth Hoste (kenneth.hoste@ugent.be)
"""
import os
import re
import socket
import sys
import travispy

from easybuild.tools.build_log import EasyBuildError
from easybuild.tools.config import init_build_options
from easybuild.tools.github import GITHUB_API_URL, GITHUB_MAX_PER_PAGE, fetch_github_token, post_comment_in_issue

from vsc.utils.generaloption import simple_option
from vsc.utils.rest import RestClient


DRY_RUN = False
TRAVIS_URL = 'https://travis-ci.org'
VERSION = '20180813.01'


def error(msg):
    """Print error message and exit."""
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def info(msg):
    """Print info message."""
    print "%s... %s" % (msg, ('', '[DRY RUN]')[DRY_RUN])


def is_travis_fluke(job_log_txt):
    """Detect fluke failures in Travis job log."""
    fluke_patterns = [
        r"Failed to connect to .* port [0-9]+: Connection timed out",
        r"fatal: unable to access .*: Failed to connect to github.com port [0-9]+: Connection timed out",
        r"Could not connect to ppa.launchpad.net.*, connection timed out",
        r"Failed to fetch .* Unable to connect to .*",
        r"Failed to fetch .* Service Unavailable",
        r"ERROR 504: Gateway Time-out",
        r"Could not connect to .*, connection timed out",
        r"No output has been received in the last [0-9]*m[0-9]*s, this potentially indicates a stalled build",
        r"curl.*SSL read: error",
        r"A TLS packet with unexpected length was received",
        r"ReadTimeoutError:.*Read timed out",
        r"ERROR 500: Internal Server Error",
        r"Some index files failed to download",
        r"Error 502: Bad Gateway",
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

    print "Checking failed Travis builds for %s/%s (using '%s' GitHub account)" % (github_account, repository, owner)

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
            print "Found %d unsuccessful jobs" % len(jobs)
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

            print "Retained %d unsuccessful jobs after filtering out flukes" % len(jobs)
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


def fetch_pr_data(github, github_account, repository, pr):
    """Fetch data for a single PR."""
    pr_data = None
    try:
        gh_repo = github.repos[github_account][repository]
        status, pr_data = gh_repo.pulls[pr].get()
        sys.stdout.write("[data]")

        # enhance PR data with test result for last commit
        pr_data['unit_test_result'] = 'UNKNOWN'
        if 'head' in pr_data:
            sha = pr_data['head']['sha']
            gh_repo = github.repos[github_account][repository]
            status, status_data = gh_repo.commits[sha].status.get()
            if status_data:
                pr_data['combined_status'] = status_data['state']
            sys.stdout.write("[status]")

        # also pull in issue comments (note: these do *not* include review comments or commit comments)
        gh_repo = github.repos[github_account][repository]
        status, comments_data = gh_repo.issues[pr].comments.get(per_page=GITHUB_MAX_PER_PAGE)
        pr_data['issue_comments'] = {
            'users': [c['user']['login'] for c in comments_data],
            'bodies': [c['body'] for c in comments_data],
        }
        sys.stdout.write("[comments], ")

    except socket.gaierror, err:
        raise EasyBuildError("Failed to download PR #%s: %s", pr, err)

    return pr_data


def comment(github, github_user, repository, pr_data, msg, check_msg=None, verbose=True):
    """Post a comment in the pull request."""
    # decode message first, if needed
    known_msgs = {
        'jok': "Jenkins: ok to test",
        'jt': "Jenkins: test this please",
    }
    if msg.startswith(':'):
        if msg[1:] in known_msgs:
            msg = known_msgs[msg[1:]]
        elif msg.startswith(':r'):
            github_login = msg[2:]
            try:
                github.users[github_login].get()
                msg = "@%s: please review?" % github_login
            except Exception:
                error("No such user on GitHub: %s" % github_login)
        else:
            error("Unknown coded comment message: %s" % msg)

    # only actually post comment if it wasn't posted before
    if check_msg:
        msg_regex = re.compile(check_msg, re.M)
        for comment in pr_data['issue_comments']['bodies']:
            if msg_regex.search(comment):
                print "Message already found (using pattern '%s'), not posting comment again!" % check_msg
                return
        print "Message not found yet (using pattern '%s'), stand back for posting!" % check_msg

    target = '%s/%s' % (pr_data['base']['repo']['owner']['login'], pr_data['base']['repo']['name'])
    if verbose:
        info("Posting comment as user '%s' in %s PR #%s: \"%s\"" % (github_user, target, pr_data['number'], msg))
    else:
        info("Posting comment as user '%s' in %s PR #%s" % (github_user, target, pr_data['number']))
    if not DRY_RUN:
        post_comment_in_issue(pr_data['number'], msg, repo=repository, github_user=github_user)
    print "Done!"


def main():

    opts = {
        'github-account': ("GitHub account where repository is located", None, 'store', 'easybuilders', 'a'),
        'github-user': ("GitHub user to use (for authenticated access)", None, 'store', 'boegel', 'u'),
        'owner': ("Owner of the bot account that is used", None, 'store', 'boegel'),
        'repository': ("Repository to use", None, 'store', 'easybuild-easyconfigs', 'r'),
    }

    go = simple_option(go_dict=opts)
    init_build_options()

    github_account = go.options.github_account
    repository = go.options.repository
    github_user = go.options.github_user
    owner = go.options.owner

    github_token = fetch_github_token(github_user)

    # prepare using GitHub API
    github = RestClient(GITHUB_API_URL, username=github_user, token=github_token, user_agent='eb-pr-check')

    res = fetch_travis_failed_builds(github_account, repository, owner, github_token)
    for pr, pr_comment, check_msg in res:
        pr_data = fetch_pr_data(github, github_account, repository, pr)
        if pr_data['state'] == 'open':
            comment(github, github_user, repository, pr_data, pr_comment, check_msg=check_msg, verbose=DRY_RUN)
        else:
            print "Not posting comment in already closed %s PR #%s" % (repository, pr)


if __name__ == '__main__':
    main()
