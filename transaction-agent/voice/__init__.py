"""Voice channel: a Bolna-facing front end over the Transaction Agent API.

Nothing in this package parses payment requests, decides approvals, or
executes transactions — see voice/adapter.py's module docstring for how it
calls into api.py instead of reimplementing any of that.
"""
