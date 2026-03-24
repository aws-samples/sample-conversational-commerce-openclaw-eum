"""
Lambda entry point — wraps the Flask WSGI app with awsgi.
"""
import awsgi
from server import app


def handler(event, context):
    return awsgi.response(app, event, context)
