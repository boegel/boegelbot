#!/usr/bin/env python3
#
# GitHub App for the EasyBuild project
#
# author: Kenneth Hoste (github.com/boegel)
#
# license: GPLv2
#
import datetime, flask, hmac, json, os, pprint, sys
from flask import Flask

SHA1 = 'sha1'


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


def handle_ping_event(request):
    """
    Handle 'ping' event
    """
    log("Ping event handled.")
    return flask.Response(status=200)


def handle_event(request):
    """
    Handle event
    """
    event_handlers = {
        'ping': handle_ping_event,
    }
    event_type = request.headers["X-GitHub-Event"]

    event_handler = event_handlers.get(event_type)
    if event_handler:
        log("Event type: %s" % event_type)
        log("Request headers: %s" % pprint.pformat(request.headers))
        log("Request body: %s" % pprint.pformat(request.json))
        event_handler(request)
    else:
        log("Unsupported event type: %s" % event_type)
        response_data = {'Unsupported event type': event_type}
        response_object = json.dumps(response_data, default=lambda obj: obj.__dict__)
        return flask.Response(response_object, status=400, mimetype='application/json')


def create_app():
    """
    Create Flask app.
    """

    app = Flask(__name__)

    @app.route('/', methods=['POST'])
    def main():
        log("%s request received!" % flask.request.method)
        verify_request(flask.request)
        handle_event(flask.request)
        return ''

    return app


if __name__ == '__main__':
    app = create_app()
    app.run()
