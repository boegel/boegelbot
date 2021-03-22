#!/usr/bin/env python3
#
# GitHub App for the EasyBuild project
# https://github.com/boegel/boegelbot (see 'app' subdirectory)
#
# author: Kenneth Hoste (@boegel)
#
# license: GPLv2
#
import datetime
import flask
import hmac
import json
import os
import pprint
import subprocess
import sys
from flask import Flask
from github import Github


DEBUG = False  # True
SHA1 = 'sha1'


class PullRequest(object):
    """Pull request object."""

    def __init__(self, pr_data, repo=None):
        """Constructor."""
        self.author = pr_data['user']['login']
        self.head_sha = pr_data['head']['sha']
        self.id = pr_data['number']
        self.repo = repo

    def __str__(self):
        """String represenation of this instance."""
        fields = ['id', 'author', 'head_sha', 'repo']
        return ', '.join(x + '=' + str(getattr(self, x)) for x in fields)


def debug_log(msg):
    """Log event data to app.log"""
    if DEBUG:
        with open('app.log', 'a') as fh:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-T%H:%M:%S")
            fh.write('DEBUG [' + timestamp + '] ' + msg + '\n')


def error(msg):
    """Print error message and exit."""
    sys.stderr.write("ERROR: %s\n" % msg)
    sys.exit(1)


def log(msg):
    """Log event data to app.log"""
    with open('app.log', 'a') as fh:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-T%H:%M:%S")
        fh.write('[' + timestamp + '] ' + msg + '\n')


def verify_request(request):
    """
    Verify request by checking webhook secret in request header.
    Webhook secret must also be available in $GITHUB_APP_SECRET_TOKEN environment variable.
    """
    # see https://docs.github.com/en/developers/webhooks-and-events/securing-your-webhooks

    webhook_secret_from_env = os.getenv('GITHUB_APP_SECRET_TOKEN')
    if webhook_secret_from_env is None:
        error("Webhook secret is not available via $GITHUB_APP_SECRET_TOKEN!")

    header_signature = request.headers.get('X-Hub-Signature')
    # if no signature is found, the request is forbidden
    if header_signature is None:
        log("Missing signature in request header => 403")
        flask.abort(403)
    else:
        signature_type, signature = header_signature.split('=')
        if signature_type == SHA1:
            # see https://docs.python.org/3/library/hmac.html
            mac = hmac.new(webhook_secret_from_env.encode(), msg=request.data, digestmod=SHA1)
            if hmac.compare_digest(str(mac.hexdigest()), str(signature)):
                log("Request verified: signature OK!")
            else:
                log("Faulty signature in request header => 403")
                flask.abort(403)
        else:
            # we only know how to verify a SHA1 signature
            log("Uknown type of signature (%s) => 501" % signature_type)
            flask.abort(501)


def handle_check_run_event(gh, request):
    """
    Handle 'check_run' event
    """
    debug_log("Request body: %s" % pprint.pformat(request.json))
    check_run_data = {
        'action': request.json['action'],
        'app_name': request.json['check_run']['app']['name'],
        'app_slug': request.json['check_run']['app']['slug'],
        'conclusion': request.json['check_run']['conclusion'],
        'html_url': request.json['check_run']['html_url'],
        'name': request.json['check_run']['name'],
        'repo': request.json['repository']['full_name'],
        'status': request.json['check_run']['status'],
    }
    pull_requests = request.json['check_run'].get('pull_requests', [])
    if pull_requests:
        check_run_data['pr_id'] = pull_requests[0]['number']
    log("Check run event handled: %s" % pprint.pformat(check_run_data))


def handle_check_suite_event(gh, request):
    """
    Handle 'check_suite' event
    """
    debug_log("Request body: %s" % pprint.pformat(request.json))
    check_suite_data = {
        'action': request.json['action'],
        'app_name': request.json['check_suite']['app']['name'],
        'app_slug': request.json['check_suite']['app']['slug'],
        'conclusion': request.json['check_suite']['conclusion'],
        'repo': request.json['repository']['full_name'],
        'status': request.json['check_suite']['status'],
    }
    pull_requests = request.json['check_suite'].get('pull_requests', [])
    if pull_requests:
        check_suite_data['pr_id'] = pull_requests[0]['number']

    log("Check suite event handled: %s" % pprint.pformat(check_suite_data))


def handle_ping_event(gh, request):
    """
    Handle 'ping' event
    """
    log("Ping event handled.")
    return flask.Response(status=200)


def handle_pr_label_event(gh, request, pr):
    """
    Handle adding of a label to a pull request.
    """
    debug_log("Request body: %s" % pprint.pformat(request.json))

    action = request.json['action']
    label_name = request.json['label']['name']
    user = request.json['sender']['login']

    log("%(repo)s PR #%(id)s %(action)s by %(user)s: %(label)s" % {
        'action': action,
        'repo': pr.repo,
        'id': pr.id,
        'label': label_name,
        'user': user,
    })

    hostname = os.environ.get('HOSTNAME', 'UNKNOWN_HOSTNAME')

    # only react if label was added by @boegel, is a 'test:*' label, and matches current host
    if action == 'labeled' and user == 'boegel' and label_name.startswith('test:' + hostname):

        repo = gh.get_repo(pr.repo)
        issue = repo.get_issue(pr.id)

        pr_target_account = request.json['repository']['owner']['login']

        cmd = [
            'eb',
            '--from-pr',
            str(pr.id),
            '--robot',
            '--force',
            '--upload-test-report',
        ]

        if pr_target_account != 'easybuilders':
            cmd.extend([
                '--pr-target-account',
                pr_target_account,
            ])

        log("Testing %s PR #%d by request of %s by running: %s" % (pr.repo, pr.id, user, ' '.join(cmd)))

        msg_lines = [
            "Fine, fine, I'm on it.",
            "Started command: `%s`" % ' '.join(cmd),
        ]

        issue.create_comment('\n'.join(msg_lines))

        process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        process
        stderr, stdout, exit_code = process.stderr, process.stdout, process.returncode

        log("Command '%s' completed, exit code %s" % (' '.join(cmd), exit_code))
        log("Stdout:\n" + stdout)
        log("Stderr:\n" + stderr)


def handle_pr_opened_event(gh, request, pr):
    """
    Handle opening of a pull request.
    """
    log("PR #%s opened in %s by %s" % (pr.id, pr.repo, pr.author))


def handle_pr_event(gh, request):
    """
    Handle 'pull_request' event
    """
    pr = PullRequest(request.json['pull_request'], repo=request.json['repository']['full_name'])
    action = request.json['action']
    log("PR action: %s" % action)
    log("PR data: %s" % pr)

    handlers = {
        'labeled': handle_pr_label_event,
        'opened': handle_pr_opened_event,
        'unlabeled': handle_pr_label_event,
    }
    handler = handlers.get(action)
    if handler:
        log("Handling PR action '%s' for %s PR #%d..." % (action, pr.repo, pr.id))
        handler(gh, request, pr)
    else:
        log("No handler for PR action '%s'" % action)

    return flask.Response(status=200)


def handle_workflow_run_event(gh, request):
    """
    Handle 'workflow_run' event
    """
    debug_log("Request body: %s" % pprint.pformat(request.json))
    workflow_run_data = {
        'action': request.json['action'],
        'conclusion': request.json['workflow_run']['conclusion'],
        'html_url': request.json['workflow_run']['html_url'],
        'repo': request.json['repository']['full_name'],
        'status': request.json['workflow_run']['status'],
        'workflow_name': request.json['workflow']['name'],
        'workflow_path': request.json['workflow']['path'],
    }
    pull_requests = request.json['workflow_run'].get('pull_requests', [])
    if pull_requests:
        workflow_run_data['pr_id'] = pull_requests[0]['number']

    log("Workflow run event handled: %s" % pprint.pformat(workflow_run_data))


def handle_event(gh, request):
    """
    Handle event
    """
    event_handlers = {
        'check_run': handle_check_run_event,
        'check_suite': handle_check_suite_event,
        'ping': handle_ping_event,
        'pull_request': handle_pr_event,
        'workflow_run': handle_workflow_run_event,
    }
    event_type = request.headers["X-GitHub-Event"]

    event_handler = event_handlers.get(event_type)
    if event_handler:
        log("Event type: %s" % event_type)
        # log("Request headers: %s" % pprint.pformat(request.headers))
        # log("Request body: %s" % pprint.pformat(request.json))
        event_handler(gh, request)
    else:
        log("Unsupported event type: %s" % event_type)
        response_data = {'Unsupported event type': event_type}
        response_object = json.dumps(response_data, default=lambda obj: obj.__dict__)
        return flask.Response(response_object, status=400, mimetype='application/json')


def create_app(gh):
    """
    Create Flask app.
    """

    app = Flask(__name__)

    @app.route('/', methods=['POST'])
    def main():
        log("%s request received!" % flask.request.method)
        verify_request(flask.request)
        handle_event(gh, flask.request)
        return ''

    return app


def main():
    """Main function."""

    gh = Github(os.getenv('GITHUB_TOKEN'))
    return create_app(gh)


if __name__ == '__main__':
    app = main()
    app.run()
