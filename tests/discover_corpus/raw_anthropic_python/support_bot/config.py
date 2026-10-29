import os

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")
KB_DB_PATH = os.getenv("KB_DB_PATH", "/var/lib/helpdesk/kb.sqlite3")
TICKETS_DB_PATH = os.getenv("TICKETS_DB_PATH", "/var/lib/helpdesk/tickets.sqlite3")
SLACK_WEBHOOK_URL = os.environ["SLACK_ONCALL_WEBHOOK"]
MAX_TOOL_ROUNDS = 6
