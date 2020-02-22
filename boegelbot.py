#!/usr/bin/env python
"""
A bot that helps out with incoming contributions to the EasyBuild project

author: Kenneth Hoste (kenneth.hoste@ugent.be)
"""
import datetime
import os
import re
import socket
import sys
import travispy
from pprint import pformat, pprint

from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import init_build_options
from easybuild.tools.github import GITHUB_API_URL, GITHUB_MAX_PER_PAGE, fetch_github_token, post_comment_in_issue
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_system_info

from easybuild.base.generaloption import simple_option
from easybuild.base.rest import RestClient


DRY_RUN = False
TRAVIS_URL = 'https://travis-ci.org'
VERSION = '20180813.01'

MODE_CHECK_TRAVIS = 'check_travis'
MODE_TEST_PR = 'test_pr'


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


def fetch_pr_data(github, github_account, repository, pr, verbose=True):
    """Fetch data for a single PR."""
    pr_data = None
    try:
        gh_repo = github.repos[github_account][repository]
        status, pr_data = gh_repo.pulls[pr].get()
        if verbose:
            sys.stdout.write("[data]")

        # enhance PR data with test result for last commit
        pr_data['unit_test_result'] = 'UNKNOWN'
        if 'head' in pr_data:
            sha = pr_data['head']['sha']
            gh_repo = github.repos[github_account][repository]
            status, status_data = gh_repo.commits[sha].status.get()
            if status_data:
                pr_data['combined_status'] = status_data['state']
            if verbose:
                sys.stdout.write("[status]")

        # also pull in issue comments (note: these do *not* include review comments or commit comments)
        gh_repo = github.repos[github_account][repository]
        status, comments_data = gh_repo.issues[pr].comments.get()
        pr_data['issue_comments'] = {
            'users': [c['user']['login'] for c in comments_data],
            'bodies': [c['body'] for c in comments_data],
        }
        if verbose:
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
        msg_regex = re.compile(re.escape(check_msg), re.M)
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


def check_notifications(github, github_user, github_account, repository):
    """
    Check notification for specified repository (and act on them).
    """
    print("Checking notifcations... (current time: %s)" % datetime.datetime.now())

    status, res = github.notifications.get(per_page=GITHUB_MAX_PER_PAGE)

    print("Found %d unread notifications" % len(res))

    # only retain stuff we care about
    notifications = []
    for elem in res:
        notifications.append({
            'full_repo_name': elem['repository']['full_name'],
            'reason': elem['reason'],
            'subject': elem['subject'],
            'unread': elem['unread'],
        })

    # filter notifications on repository:
    # - only notifications for repo we care about
    # - only notifications for mentions
    full_repo_name = github_account + '/' + repository
    retained = []
    for notification in notifications:
        if notification['full_repo_name'] == full_repo_name and notification['subject']['type'] == 'PullRequest':
            if notification['reason'] == 'mention':
                retained.append(notification)
    print("Retained %d relevant notifications after filtering" % len(retained))

    return retained


def process_notifications(notifications, github, github_user, github_account, repository):
    """Process provided notifications."""

    res = []

    cnt = len(notifications)
    for idx, notification in enumerate(notifications):
        pr_title = notification['subject']['title']
        pr_id = notification['subject']['url'].split('/')[-1]
        print("[%d/%d] Processing notification for %s PR #%s \"%s\"..." % (idx+1, cnt, repository, pr_id, pr_title))

        # check comments (latest first)
        pr_data = fetch_pr_data(github, github_account, repository, pr_id, verbose=False)

        comments = zip(pr_data['issue_comments']['users'], pr_data['issue_comments']['bodies'])

        mention_regex = re.compile(r'\s*@%s:?\s*' % github_user, re.M)

        mention_found = False
        for comment_by, comment_txt in comments[::-1]:
            if mention_regex.search(comment_txt):
                msg = mention_regex.sub('', comment_txt)
                if "please test" in msg:
                    system_info = get_system_info()
                    hostname = system_info.get('hostname', '(hostname not known)')
                    reply_msg = "Test report from %s coming up soon (not really, just testing)..." % hostname
                else:
                    reply_msg = "Got message \"%s\", but I don't know what to do with it, sorry..." % msg

                comment(github, github_user, repository, pr_data, reply_msg, check_msg=reply_msg, verbose=DRY_RUN)

                mention_found = True
                break
            else:
                # skip irrelevant comments (no mention found)
                continue

        if not mention_found:
            print_warning("Relevant comment for notification #%d for PR %s not found?!" % (idx, pr_id))
            sys.stderr.write("Notification data:\n" + pformat(notification))

    return res


def main():

    opts = {
        'github-account': ("GitHub account where repository is located", None, 'store', 'easybuilders', 'a'),
        'github-user': ("GitHub user to use (for authenticated access)", None, 'store', 'boegel', 'u'),
        'mode': ("Mode to run in", 'choice', 'store', MODE_CHECK_TRAVIS, [MODE_CHECK_TRAVIS, MODE_TEST_PR]),
        'owner': ("Owner of the bot account that is used", None, 'store', 'boegel'),
        'repository': ("Repository to use", None, 'store', 'easybuild-easyconfigs', 'r'),
    }

    go = simple_option(go_dict=opts)
    init_build_options()

    github_account = go.options.github_account
    github_user = go.options.github_user
    mode = go.options.mode
    owner = go.options.owner
    owner = go.options.owner
    repository = go.options.repository

    github_token = fetch_github_token(github_user)

    # prepare using GitHub API
    github = RestClient(GITHUB_API_URL, username=github_user, token=github_token, user_agent='eb-pr-check')

    if mode == MODE_CHECK_TRAVIS:
        res = fetch_travis_failed_builds(github_account, repository, owner, github_token)
        for pr, pr_comment, check_msg in res:
            pr_data = fetch_pr_data(github, github_account, repository, pr)
            if pr_data['state'] == 'open':
                comment(github, github_user, repository, pr_data, pr_comment, check_msg=check_msg, verbose=DRY_RUN)
            else:
                print "Not posting comment in already closed %s PR #%s" % (repository, pr)

    elif mode == MODE_TEST_PR:
        notifications = check_notifications(github, github_user, github_account, repository)
        process_notifications(notifications, github, github_user, github_account, repository)
    else:
        error("Unknown mode: %s" % mode)

if __name__ == '__main__':
    main()
