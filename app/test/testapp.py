import copy
import flask
import github
import os

from app import PullRequest, handle_check_run_event, handle_check_suite_event
from app import handle_event, handle_workflow_run_event


CHECK_RUN_EVENT = {
    'action': 'created',
    'check_run': {
        'app': {
            'name': 'GitHub Actions',
            'slug': 'github-actions',
        },
        'conclusion': None,
        'html_url': 'https://github.com/boegel/easybuild-easyconfigs/runs/1138537767',
        'name': 'test-suite (2.7, Lmod-8.1.14, Lua)',
        'pull_requests': [],
        'status': 'queued',
    },
    'repository': {'full_name': 'boegel/boegelbot'},
}

CHECK_SUITE_EVENT = {
    'action': 'completed',
    'check_suite': {
        'app': {
            'name': 'GitHub Actions',
            'slug': 'github-actions',
        },
        'conclusion': 'failure',
        'pull_requests': [],
        'status': 'queued',
    },
    'repository': {'full_name': 'boegel/boegelbot'},
}

PING_EVENT = {}

PULL_REQUEST_OPENED_EVENT = {
    'action': 'opened',
    'pull_request': {
        'user': {'login': 'boegel'},
        'number': 75,
        'head': {'sha': '662e87628812fdcf77caffbeb723b3f840ea54a5'},
    },
    'repository': {'full_name': 'boegel/easybuild-easyconfigs'},
    'sender': {'login': 'boegel'},
}

PULL_REQUEST_LABELED_EVENT = copy.deepcopy(PULL_REQUEST_OPENED_EVENT)
PULL_REQUEST_LABELED_EVENT['action'] = 'labeled'
PULL_REQUEST_LABELED_EVENT['label'] = {'name': 'test'}

WORKFLOW_RUN_EVENT = {
    'action': 'requested',
    'workflow': {
        'name': 'Static Analysis',
        'path': '.github/workflows/linting.yml',
    },
    'workflow_run': {
        'conclusion': None,
        'html_url': 'https://github.com/boegel/easybuild-easyconfigs/actions/runs/262903191',
        'pull_requests': [],
        'status': 'queued',
    },
    'repository': {'full_name': 'boegel/boegelbot'},
}


class FakeRequest(object):

    def __init__(self, event_type, json_data):
        self.headers = {'X-GitHub-Event': event_type}
        self.json = json_data


def test_pr():
    pr_data = {
        'head': {'sha': '662e87628812fdcf77caffbeb723b3f840ea54a5'},
        'number': 123,
        'user': {'login': 'boegel'},
    }
    pr = PullRequest(pr_data, repo='boegel/boegelbot')

    assert pr.author == 'boegel'
    assert pr.head_sha == '662e87628812fdcf77caffbeb723b3f840ea54a5'
    assert pr.id == 123
    assert pr.repo == 'boegel/boegelbot'

    pr_str = 'id=123, author=boegel, '
    pr_str += 'head_sha=662e87628812fdcf77caffbeb723b3f840ea54a5, '
    pr_str += 'repo=boegel/boegelbot'
    assert str(pr) == pr_str


def test_handle_check_run_event():
    gh = None
    json_data = copy.deepcopy(CHECK_RUN_EVENT)
    request = FakeRequest('check_run', json_data)
    handle_check_run_event(gh, request)

    json_data['check_run']['pull_requests'] = [{'number': 12345}]
    request = FakeRequest('check_run', json_data)
    handle_check_run_event(gh, request)


def test_handle_check_suite_event():
    gh = None
    json_data = copy.deepcopy(CHECK_SUITE_EVENT)
    request = FakeRequest('check_suite', json_data)
    handle_check_suite_event(gh, request)

    json_data['check_suite']['pull_requests'] = [{'number': 12345}]
    request = FakeRequest('check_suite', json_data)
    handle_check_suite_event(gh, request)


def test_handle_workflow_run_event():
    gh = None
    json_data = copy.deepcopy(WORKFLOW_RUN_EVENT)
    request = FakeRequest('workflow_run', json_data)
    handle_workflow_run_event(gh, request)

    json_data['workflow_run']['pull_requests'] = [{'number': 12345}]
    request = FakeRequest('workflow_run', json_data)
    handle_workflow_run_event(gh, request)


def test_handle_event(monkeypatch):

    def fake_create_comment(_, msg):
        comments.append(msg)

    monkeypatch.setattr(github.Issue.Issue, 'create_comment', fake_create_comment)

    gh = github.Github(os.getenv('GITHUB_TOKEN'))
    events = {
        'check_run': CHECK_RUN_EVENT,
        'check_suite': CHECK_SUITE_EVENT,
        'ping': PING_EVENT,
        'workflow_run': WORKFLOW_RUN_EVENT,
    }
    for event_type in events:
        request = FakeRequest(event_type, events[event_type])
        handle_event(gh, request)

    # test handling of PR events
    request = FakeRequest('pull_request', PULL_REQUEST_OPENED_EVENT)
    handle_event(gh, request)

    request = FakeRequest('pull_request', PULL_REQUEST_LABELED_EVENT)
    handle_event(gh, request)

    # check handling of unsupported events
    request = FakeRequest('unknown_event_type', {})
    res = handle_event(gh, request)
    assert isinstance(res, flask.Response)
    assert res.status_code == 400
    assert res.data == b'{"Unsupported event type": "unknown_event_type"}'
