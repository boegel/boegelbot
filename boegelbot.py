#!/usr/bin/env python
"""
A bot that helps out with incoming contributions to the EasyBuild project

author: Kenneth Hoste (kenneth.hoste@ugent.be)
"""
import datetime
import os
import re
import shlex
import socket
import sys
from pprint import pformat, pprint

try:
    import travispy
except ImportError:
    pass

from easybuild.tools.build_log import EasyBuildError, print_warning
from easybuild.tools.config import init_build_options
from easybuild.tools.github import GITHUB_API_URL, GITHUB_MAX_PER_PAGE, fetch_github_token, post_comment_in_issue
from easybuild.tools.py2vs3 import HTTPError
from easybuild.tools.github import GITHUB_PR_STATE_OPEN, STATUS_PENDING, STATUS_SUCCESS, fetch_pr_data
from easybuild.tools.run import run_cmd
from easybuild.tools.systemtools import get_system_info

from easybuild.base.generaloption import simple_option
from easybuild.base.rest import RestClient


DRY_RUN = False
TRAVIS_URL = 'https://travis-ci.org'
VERSION = '20200716.01'

MODE_CHECK_GITHUB_ACTIONS = 'check_github_actions'
MODE_CHECK_TRAVIS = 'check_travis'
MODE_TEST_PR = 'test_pr'

# see https://github.com/easybuilders/easybuild-containers
CONTAINER_BASE_URL = 'docker://ghcr.io/easybuilders'


def error(msg):
    """Print error message and exit."""
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def warning(msg):
    """Print warning message."""
    sys.stderr.write("WARNING: %s\n" % msg)


def info(msg):
    """Print info message."""
    print("%s... %s" % (msg, ('', '[DRY RUN]')[DRY_RUN]))


def is_fluke(job_log_txt):
    """Detect fluke failures in Travis job log."""
    fluke_patterns = [
        # Travis fluke failures
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
        # GitHub Actions fluke failures
        r"500 \(Internal Server Error\)",
        r"failed: Connection timed out",  # for downloading stuff from SourceForge
        r"unable to resolve host address",  # DNS issues
        r"fetch-pack: unexpected disconnect",
        r"Internal Server Error occurred while resolving",
    ]
    fluke = False
    for pattern in fluke_patterns:
        regex = re.compile(pattern, re.M)
        if regex.search(job_log_txt):
            print("Fluke found: '%s'" % regex.pattern)
            fluke = True
            break

    return fluke


def fetch_travis_failed_builds(github_account, repository, owner, github_token):
    """Scan Travis test runs for failures, and return notification to be sent to PR if one is found"""

    if 'travispy' not in globals():
        error("travisy not available?!")

    travis = travispy.TravisPy.github_auth(github_token)

    print("Checking failed Travis builds for %s/%s (using '%s' GitHub account)" % (github_account, repository, owner))

    repo_slug = '%s/%s' % (github_account, repository)
    last_builds = travis.builds(slug=repo_slug, event_type='pull_request')

    done_prs = []

    res = []
    for build in last_builds:
        bid, pr = build.number, build.pull_request_number

        if pr in done_prs:
            print("(skipping test suite run for already processed PR #%s)" % pr)
            continue

        done_prs.append(pr)

        if build.successful:
            print("(skipping successful test suite run %s for PR %s)" % (bid, pr))

        else:
            build_url = os.path.join(TRAVIS_URL, repo_slug, 'builds', str(build.id))
            print("[id: %s] PR #%s - %s - %s" % (bid, pr, build.state, build_url))

            jobs = [(str(job_id), travis.jobs(ids=[job_id])[0]) for job_id in sorted(build.job_ids)]
            jobs_ok = [job.successful for (_, job) in jobs]

            pr_comment = "Travis test report: %d/%d runs failed - " % (jobs_ok.count(False), len(jobs))
            pr_comment += "see %s\n" % build_url
            check_msg = pr_comment.strip()

            jobs = [(job_id, job) for (job_id, job) in jobs if job.unsuccessful]
            print("Found %d unsuccessful jobs" % len(jobs))
            if jobs:

                # detect fluke failures in jobs, and restart them
                flukes = []
                for (job_id, job) in jobs:
                    if is_fluke(job.log.body):
                        flukes.append(job_id)

                if flukes:
                    boegel_gh_token = fetch_github_token('boegel')
                    if boegel_gh_token:
                        travis_boegel = travispy.TravisPy.github_auth(boegel_gh_token)
                        for (job_id, job) in zip(flukes, travis_boegel.jobs(ids=flukes)):
                            print("[id %s] PR #%s - fluke detected in job ID %s, restarting it!" % (bid, pr, job_id))
                            if job.restart():
                                print("Job ID %s restarted" % job_id)
                            else:
                                print("Failed to restart job ID %s!" % job_id)

                        # filter out fluke jobs, we shouldn't report these
                        jobs = [(job_id, job) for (job_id, job) in jobs if job_id not in flukes]
                    else:
                        print("Can't restart Travis jobs that failed due to flukes, no GitHub token found")

            print("Retained %d unsuccessful jobs after filtering out flukes" % len(jobs))
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
                pr_comment += "Please talk to my owner `@%s` if you notice me acting stupid)," % owner
                pr_comment += "or submit a pull request to https://github.com/boegel/boegelbot fix the problem."

                res.append((pr, pr_comment, check_msg))

            else:
                print("(no more failed jobs after filtering out flukes for id %s PR #%s)" % (bid, pr))

    print("Processed %d builds, found %d PRs with failed builds to report back on" % (len(last_builds), len(res)))

    return res


def fetch_github_failed_workflows(github, github_account, repository, github_user, owner):
    """Scan GitHub Actions for failed workflow runs."""

    res = []

    # only consider failed workflows triggered by pull requests
    params = {
        'event': 'pull_request',
        # filtering based on status='failure' no longer works correctly?!
        # also with status='completed' some workflow runs are not included in result...
        # 'status': 'failure',
        'per_page': GITHUB_MAX_PER_PAGE,
    }

    try:
        status, run_data = github.repos[github_account][repository].actions.runs.get(**params)
    except socket.gaierror as err:
        error("Failed to download GitHub Actions workflow runs data: %s" % err)

    if status == 200:
        run_data = list(run_data['workflow_runs'])
        print("Found %s failed workflow runs for %s/%s" % (len(run_data), github_account, repository))
    else:
        error("Status for downloading GitHub Actions workflow runs data should be 200, got %s" % status)

    failing_prs = set()

    for idx, entry in enumerate(run_data):

        if entry['status'] != 'completed':
            print("Ignoring incomplete workflow run %s" % entry['html_url'])
            continue

        if entry['conclusion'] == 'success':
            print("Ignoring successful workflow run %s" % entry['html_url'])
            continue

        head_user = entry['head_repository']['owner']['login']
        head = '%s:%s' % (head_user, entry['head_branch'])
        head_sha = entry['head_sha']

        # determine corresponding PR (if any)
        status, pr_data = github.repos[github_account][repository].pulls.get(head=head)
        if status != 200:
            error("Status for downloading data for PR with head %s should be 200, got %s" % (head, status))

        if len(pr_data) == 1:
            pr_data = pr_data[0]
            print("Failed workflow run %s found (PR: %s)" % (entry['html_url'], pr_data['html_url']))

            pr_id = pr_data['number']

            # skip PRs for which a failing workflow was already encountered
            if pr_id in failing_prs:
                print("PR #%s already encountered, so skipping workflow %s" % (pr_id, entry['html_url']))
                continue

            pr_data, _ = fetch_pr_data(pr_id, github_account, repository, github_user, full=True,
                                       per_page=GITHUB_MAX_PER_PAGE)

            if pr_data['state'] == 'open':

                pr_head_sha = pr_data['head']['sha']

                # make sure workflow was run for latest commit in this PR
                if head_sha != pr_head_sha:
                    msg = "Workflow %s was for commit %s, " % (entry['html_url'], head_sha)
                    msg += "not latest commit in PR #%s (%s), so skipping" % (pr_id, pr_head_sha)
                    print(msg)
                    continue

                # check status of most recent commit in this PR,
                # ignore this PR if status is "success" or "pending"
                pr_status = pr_data['status_last_commit']
                print("Status of last commit (%s) in PR #%s: %s" % (pr_head_sha, pr_id, pr_status))

                if pr_status in ['action_required', STATUS_PENDING, STATUS_SUCCESS]:
                    print("Status of last commit in PR #%s is '%s', so ignoring it for now..." % (pr_id, pr_status))
                    continue

                # download list of jobs in workflow
                run_id = entry['id']
                status, jobs_data = github.repos[github_account][repository].actions.runs[run_id].jobs.get()
                if status != 200:
                    error("Failed to download list of jobs for workflow run %s" % entry['html_url'])

                # determine ID of first failing job
                job_id = None
                for job in jobs_data['jobs']:
                    if job['conclusion'] == 'failure':
                        job_id = job['id']
                        print("Found failing job for workflow %s: %s" % (entry['html_url'], job_id))
                        break

                if job_id is None:
                    error("ID of failing job not found for workflow %s" % entry['html_url'])

                status = None
                try:
                    status, log_txt = github.repos[github_account][repository].actions.jobs[job_id].logs.get()
                    log_txt = log_txt.decode(errors='ignore')
                except HTTPError as err:
                    status = err.code

                if status == 200:
                    print("Downloaded log for job %s" % job_id)
                else:
                    warning("Failed to download log for job %s" % job_id)
                    log_txt = '(failed to fetch log contents due to HTTP status code %s)' % status

                # strip off timestamp prefixes
                # example timestamp: 2020-07-13T09:54:36.5004935Z
                timestamp_regex = re.compile(r'^[0-9-]{10}T[0-9:]{8}\.[0-9]+Z ')
                log_lines = [timestamp_regex.sub('', x) for x in log_txt.splitlines()]

                # determine line that marks end of output for failing test suite:
                # "ERROR: Not all tests were successful"
                error_line_idx = None
                for idx, line in enumerate(log_lines):
                    if line.startswith("ERROR: Not all tests were successful"):
                        error_line_idx = idx
                        print("Found error line @ index %s" % error_line_idx)
                        break

                if error_line_idx is None:
                    log_txt_clean = '\n'.join(log_lines)
                    warning("Log line that marks end of test suite output not found for job %s!\n%s" % (job_id, log_txt_clean))
                    if is_fluke(log_txt):
                        owner_gh_token = fetch_github_token(owner)
                        if owner_gh_token:
                            github_owner = RestClient(GITHUB_API_URL, username=owner, token=owner_gh_token,
                                                      user_agent='eb-pr-check')
                            print("Fluke found, restarting this workflow using @%s's GitHub account..." % owner)
                            repo_api = github_owner.repos[github_account][repository]
                            # note: this must be one line
                            # have to use __getattr__ because rerun-failed-jobs includes dashes
                            # cfr. https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#re-run-a-workflow
                            status, _  = repo_api.__getattr__('actions/runs/%s/rerun-failed-jobs' % run_id).post()
                            if status == 201:
                                print("Failed jobs for workflow %s restarted" % entry['html_url'])
                            else:
                                print("Failed to restart failed jobs for workflow %s: status %s" % (entry['html_url'], status))
                        else:
                            warning("Fluke found but can't restart workflow, no token found for @%s" % owner)

                    continue

                # find line that marks start of test output: only dots and 'E'/'F' characters
                start_test_regex = re.compile(r'^[\.EF]+$')
                start_line_idx = error_line_idx
                start_log_line = log_lines[start_line_idx]
                while(start_line_idx >= 0 and not (start_log_line and start_test_regex.match(start_log_line))):
                    start_line_idx -= 1
                    start_log_line = log_lines[start_line_idx]

                log_lines = log_lines[start_line_idx+1:error_line_idx+1]

                # compose comment
                pr_comment = "@%s: Tests failed in GitHub Actions" % pr_data['user']['login']
                pr_comment += ", see %s" % entry['html_url']

                # use first part of comment to check whether comment was already posted
                check_msg = pr_comment

                if len(log_lines) > 100:
                    log_lines = log_lines[-100:]
                    pr_comment += "\nLast 100 lines of output from first failing test suite run:\n\n```"
                else:
                    pr_comment += "\nOutput from first failing test suite run:\n\n```"

                for line in log_lines:
                    pr_comment += line + '\n'

                pr_comment += "```\n"

                pr_comment += "\n*bleep, bloop, I'm just a bot (boegelbot v%s)*\n" % VERSION
                pr_comment += "Please talk to my owner `@%s` if you notice me acting stupid),\n" % owner
                pr_comment += "or submit a pull request to https://github.com/boegel/boegelbot fix the problem."

                res.append((pr_id, pr_comment, check_msg))
                failing_prs.add(pr_id)
            else:
                print("Ignoring failed workflow run for closed PR %s" % pr_data['html_url'])
        else:
            warning("Expected exactly one PR with head %s, found %s: %s" % (head, len(pr_data), pr_data))

    print("Processed %d failed workflow runs, found %d PRs to report back on" % (len(run_data), len(res)))

    return res


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
        for comment in pr_data['issue_comments']:
            if msg_regex.search(comment['body']):
                msg = "Message already found (using pattern '%s'), " % check_msg
                msg += "not posting comment again to PR %s!" % pr_data['number']
                print(msg)
                return
        print("Message not found yet (using pattern '%s'), stand back for posting!" % check_msg)

    target = '%s/%s' % (pr_data['base']['repo']['owner']['login'], pr_data['base']['repo']['name'])
    if verbose:
        info("Posting comment as user '%s' in %s PR #%s: \"%s\"" % (github_user, target, pr_data['number'], msg))
    else:
        info("Posting comment as user '%s' in %s PR #%s" % (github_user, target, pr_data['number']))
    if not DRY_RUN:
        post_comment_in_issue(pr_data['number'], msg, repo=repository, github_user=github_user)
    print("Done!")


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
            'thread_id': elem['id'],
            'timestamp': elem['updated_at'],
            'unread': elem['unread'],
        })

    # filter notifications:
    # - only notifications for repo we care about
    # - only notifications for mentions
    # - only notifications for pull requests
    full_repo_name = github_account + '/' + repository
    retained = []
    for notification in notifications:
        if notification['full_repo_name'] == full_repo_name and notification['subject']['type'] == 'PullRequest':
            if notification['reason'] == 'mention':
                retained.append(notification)
    print("Retained %d relevant notifications after filtering" % len(retained))

    return retained


def process_notifications(notifications, github, github_user, github_account, repository, host, gpuhost, pr_test_cmd, core_cnt, gpu_job_opt):
    """Process provided notifications."""

    res = []

    cnt = len(notifications)
    for idx, notification in enumerate(notifications):
        pr_title = notification['subject']['title']
        pr_id = notification['subject']['url'].split('/')[-1]
        msg = "[%d/%d] Processing notification for %s PR #%s \"%s\"... " % (idx+1, cnt, repository, pr_id, pr_title)
        msg += "(thread id: %s, timestamp: %s)" % (notification['thread_id'], notification['timestamp'])
        print(msg)

        # check comments (latest first)
        pr_data, _ = fetch_pr_data(pr_id, github_account, repository, github_user, full=True,
                                   per_page=GITHUB_MAX_PER_PAGE)

        comments_data = pr_data['issue_comments']

        # determine comment that triggered the notification
        trigger_comment_id = None
        mention_regex = re.compile(r'^\s*@%s:?\s*' % github_user, re.M)
        for comment_data in comments_data[::-1]:
            comment_id, comment_txt = comment_data['id'], comment_data['body']
            if mention_regex.search(comment_txt):
                trigger_comment_id = comment_id
                break

        check_str = "notification for comment with ID %s processed on %s" % (trigger_comment_id, host)

        processed = False
        for comment_data in comments_data[::-1]:
            comment_by, comment_txt = comment_data['user']['login'], comment_data['body']
            if comment_by == github_user and check_str in comment_txt:
                print("check_str '%s' found in: %s" % (check_str, comment_txt))
                processed = True
                break

        if processed:
            msg = "Notification %s already processed, so skipping it... " % notification['thread_id']
            msg += "(timestamp: %s)" % notification['timestamp']
            print(msg)
            continue

        # Make sure that also only --host can be specified without --gpuhost and vice versa
        if not host:
          host = 'NO_HOST_PATTERN_PROVIDED'
        if not gpuhost:
          gpuhost = 'NO_GPUHOST_PATTERN_PROVIDED'

        host_regex = re.compile(r'@.*%s' % host, re.M)
        gpuhost_regex = re.compile(r'@.*%s' % gpuhost, re.M)

        mention_found = False
        for comment_data in comments_data[::-1]:
            comment_id, comment_by = comment_data['id'], comment_data['user']['login']
            comment_txt = comment_data['body']
            if mention_regex.search(comment_txt):
                print("Found comment including '%s': %s" % (mention_regex.pattern, comment_txt))

                msg = mention_regex.sub(' ', comment_txt)

                # require that @<host> or @<gpuhost> is included in comment before taking any action
                if host_regex.search(msg) or gpuhost_regex.search(msg):
                    print("Comment includes '%s', so processing it..." % host_regex.pattern)

                    maintainers = ['akesandgren', 'bartoldeman', 'bedroge', 'boegel', 'branfosj', 'casparvl', 'Crivella',
                                   'jfgrimm', 'lexming', 'Micket', 'migueldiascosta', 'ocaisa', 'SebastianAchilles',
                                   'smoors', 'verdurin', 'WilleBell']
                    contributors = ['robert-mijakovic', 'deniskristak', 'ItIsI-Orient', 'PetrKralCZ', 'sassy-crick',
                                    'laraPPr', 'pavelToman', 'Louwrensth', 'Thyre']
                    allowed_accounts = maintainers + contributors

                    please_regex = re.compile(r'[Pp]lease test', re.M)

                    if comment_by not in allowed_accounts:

                        allowed_accounts_str = ' or '.join('@%s' % x for x in allowed_accounts)

                        reply_msg = "@%s: I noticed your comment, " % comment_by
                        reply_msg += "but I only dance when %s tells me (for now), I'm sorry..." %  allowed_accounts_str

                    elif "PLEASE " in msg:
                        reply_msg = "Don't scream, it's rude and I don't like people who do..."
                    elif please_regex.search(msg):

                        system_info = get_system_info()
                        hostname = system_info.get('hostname', '(hostname not known)')

                        reply_msg = "@%s: Request for testing this PR well received on %s\n" % (comment_by, hostname)

                        tmpl_dict = {
                            'container': '',  # no container used by default
                            'core_cnt': core_cnt,  # use default number of cores (as specified via --core-cnt option)
                            'eb_args': '',  # no arguments to 'eb' command by default
                            'eb_branch': 'develop',  # use develop branch by default
                            'pr': pr_id,
                            'repository': repository,
                            'slurm_args': '',
                        }

                        # if running on gpuhost add gpu_job_opt to tmpl_dict
                        if gpuhost_regex.search(msg):
                            tmpl_dict.update({
                                'slurm_args': gpu_job_opt,
                            })

                        # check whether custom arguments for 'eb' or submit command are specified
                        for item in shlex.split(msg):
                            for key in ['CORE_CNT', 'EB_ARGS', 'EB_BRANCH', 'SLURM_ARGS']:
                                if item.startswith(key + '='):
                                    _, value = item.split('=', 1)
                                    tmpl_dict[key.lower()] = '"%s"' % value
                                    break

                        # check whether testing in a container image is requested
                        in_container_pattern = "[Pp]lease test @.*%s in container (?P<container>.*)" % host
                        in_container_regex = re.compile(in_container_pattern, re.M)
                        res = in_container_regex.search(msg)
                        if res:
                            tmpl_dict['container'] = CONTAINER_BASE_URL + '/' + res.group('container').strip()

                        # run pr test command, check exit code and capture output
                        cmd = pr_test_cmd % tmpl_dict
                        (out, ec) = run_cmd(cmd, simple=False)

                        reply_msg += '\n'.join([
                            '',
                            "PR test command '`%s`' executed!" % cmd,
                            "* exit code: %s" % ec,
                            "* output:",
                            "```",
                            out.strip(),
                            "```",
                            '',
                            "Test results coming soon (I hope)...",
                        ])

                    else:
                        reply_msg = "Got message \"%s\", but I don't know what to do with it, sorry..." % msg

                    # always include 'details' part than includes a check string
                    # which includes the ID of the comment we're reacting to,
                    # so we can avoid re-processing the same comment again...
                    reply_msg += '\n'.join([
                        '',
                        '',
                        "<details>",
                        '',
                        "*- %s*" % check_str,
                        '',
                        "*Message to humans: this is just bookkeeping information for me,",
                        "it is of no use to you (unless you think I have a bug, which I don't).*",
                        "</details>",
                    ])

                    comment(github, github_user, repository, pr_data, reply_msg, verbose=DRY_RUN)
                else:
                    print("Pattern '%s' not found in comment for PR #%s, so ignoring it" % (host_regex.pattern, pr_id))

                mention_found = True
                break
            else:
                # skip irrelevant comments (no mention found)
                print("Pattern '%s' not found in comment for PR #%s, so ignoring it" % (mention_regex.pattern, pr_id))
                continue

        if not mention_found:
            print_warning("Relevant comment for notification #%d for PR %s not found?!" % (idx, pr_id))
            sys.stderr.write("Notification data:\n" + pformat(notification))

    return res


def main():

    opts = {
        'core-cnt': ("Default core count to use for jobs", None, 'store', None),
        'github-account': ("GitHub account where repository is located", None, 'store', 'easybuilders', 'a'),
        'github-user': ("GitHub user to use (for authenticated access)", None, 'store', 'boegel', 'u'),
        'mode': ("Mode to run in", 'choice', 'store', MODE_CHECK_TRAVIS,
                 [MODE_CHECK_GITHUB_ACTIONS, MODE_CHECK_TRAVIS, MODE_TEST_PR]),
        'owner': ("Owner of the bot account that is used", None, 'store', 'boegel'),
        'repository': ("Repository to use", None, 'store', 'easybuild-easyconfigs', 'r'),
        'host': ("Label for current host (used to filter comments asking to test a PR)", None, 'store', ''),
        'gpuhost': ("Label for current gpuhost (used to filter comments asking to test a PR)", None, 'store', ''),
        'pr-test-cmd': ("Command to use for testing easyconfig pull requests (should include '%(pr)s' template value)",
                        None, 'store', ''),
        'gpu-job-opt': ("Additional job option to run an a GPU node", None, 'store', None),
    }

    go = simple_option(go_dict=opts)
    init_build_options()

    github_account = go.options.github_account
    github_user = go.options.github_user
    mode = go.options.mode
    owner = go.options.owner
    owner = go.options.owner
    repository = go.options.repository
    host = go.options.host
    gpuhost = go.options.gpuhost
    pr_test_cmd = go.options.pr_test_cmd
    core_cnt = go.options.core_cnt
    gpu_job_opt = go.options.gpu_job_opt

    github_token = fetch_github_token(github_user)

    # prepare using GitHub API
    github = RestClient(GITHUB_API_URL, username=github_user, token=github_token, user_agent='eb-pr-check')

    if mode in [MODE_CHECK_GITHUB_ACTIONS, MODE_CHECK_TRAVIS]:

        if mode == MODE_CHECK_TRAVIS:
            res = fetch_travis_failed_builds(github_account, repository, owner, github_token)
        elif mode == MODE_CHECK_GITHUB_ACTIONS:
            res = fetch_github_failed_workflows(github, github_account, repository, github_user, owner)
        else:
            error("Unknown mode: %s" % mode)

        for pr, pr_comment, check_msg in res:
            params = {'per_page': GITHUB_MAX_PER_PAGE}
            pr_data, _ = fetch_pr_data(pr, github_account, repository, github_user, full=True, **params)
            if pr_data['state'] == GITHUB_PR_STATE_OPEN:
                comment(github, github_user, repository, pr_data, pr_comment, check_msg=check_msg, verbose=DRY_RUN)
            else:
                print("Not posting comment in already closed %s PR #%s" % (repository, pr))

    elif mode == MODE_TEST_PR:
        if not host:
            error("--host is required when using '--mode %s' !" % MODE_TEST_PR)

        if '%(pr)s' not in pr_test_cmd or '%(eb_args)s' not in pr_test_cmd:
            error("--pr-test-cmd should include '%%(pr)s' and '%%(eb_args)s', found '%s'" % (pr_test_cmd))

        if core_cnt is None:
            error("--core-cnt must be used to specify the default number of cores to request per submitted job!")

        notifications = check_notifications(github, github_user, github_account, repository)
        process_notifications(notifications, github, github_user, github_account, repository, host, gpuhost, pr_test_cmd,
                              core_cnt, gpu_job_opt)
    else:
        error("Unknown mode: %s" % mode)


if __name__ == '__main__':
    main()
