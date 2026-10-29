"""Side-effect badges for a tool, from what its body does (static rules), with its name as a tie-breaker.

Badges drive test drafting and safe defaults: `destructive` tools are mocked until the user says otherwise, tools
that read untrusted text get a prompt-injection scenario, tools that write data get a state check.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .pyfacts import PyModule

ORDER = ["destructive", "writes data", "external call", "reads untrusted text", "read-only"]
HTTP_WRITE = "_http_write"  # internal marker: a POST/PUT/PATCH, judged against the tool's verb in _finish

SQL_DESTRUCTIVE = re.compile(r"\b(DELETE\s+FROM|DROP\s+(TABLE|DATABASE)|TRUNCATE)\b", re.I)
SQL_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET|UPSERT|MERGE\s+INTO|REPLACE\s+INTO)\b", re.I)
SQL_READ = re.compile(r"\bSELECT\b.+\bFROM\b", re.I | re.S)

# Names are judged in snake_case (camelCase and spaces converted); verbs count when they lead the name.
VERB_DESTRUCTIVE = {"delete", "remove", "drop", "purge", "wipe", "destroy", "cancel", "charge", "pay", "transfer", "send",
                    "email", "sms", "notify", "publish", "terminate", "revoke", "ban", "deactivate", "execute",
                    "deploy", "merge", "book", "reset", "close", "block", "freeze", "suspend", "lock", "disable",
                    "restart", "rollback", "shutdown", "kill", "stop", "unsubscribe", "refund", "wire", "post"}
NOUN_DESTRUCTIVE = {"refund", "payout", "payment", "password", "shell", "command"}  # destructive wherever they appear
VERB_WRITE = {"create", "add", "insert", "update", "set", "write", "save", "edit", "modify", "reserve", "place", "submit",
              "assign", "upsert", "patch", "upload", "register", "enroll", "schedule", "apply", "approve", "reject",
              "issue", "append", "import", "file", "put", "log", "record", "store", "mark", "tag", "open", "rename",
              "move", "change", "generate"}
VERB_READ = {"get", "list", "search", "find", "read", "fetch", "lookup", "look", "query", "show", "describe", "check",
             "count", "retrieve", "view", "calculate", "compute", "estimate", "summarize", "explain", "track", "monitor",
             "analyze", "compare", "inspect", "load", "download", "browse", "scrape", "crawl", "convert", "translate", "run"}
SENDING = re.compile(r"(^|_)(send|email|mail|sms|notify|post_message|slack|tweet|publish)($|_)")
# what outside text looks like: documents, pages, messages, logs (a search for flights or a weather lookup is data)
UNTRUSTED_NOUN = re.compile(r"(^|_)(web|url|urls|page|pages|html|browse|scrape|crawl|help|helpcenter|article|articles|"
                            r"docs?|document|documents|readme|issue|issues|arxiv|paper|papers|news|email|emails|mail|"
                            r"inbox|comment|comments|review|reviews|posts?|filings?|release|notes|ticket|tickets|kb|"
                            r"knowledge|wiki|forum|feed|rss|transcript|log|logs|receipt|content|website|competitor|repo)($|_)")


def snake(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).replace("-", "_").replace(" ", "_").replace(".", "_")).lower()

DESTRUCTIVE_CALLS = ("rmtree", "os.remove", "os.unlink", ".unlink", "os.rmdir", "subprocess.run", "subprocess.call",
                     "subprocess.Popen", "subprocess.check_output", "os.system", "smtplib.SMTP", ".sendmail",
                     ".send_message", "send_mail", ".delete_one", ".delete_many", ".drop", ".refunds.create",
                     ".charges.create", ".payment_intents.create", ".transfers.create", ".messages.create")
WRITE_CALLS = (".add", ".add_all", ".commit", ".save", ".insert", ".insert_one", ".insert_many", ".update_one",
               ".update_many", ".bulk_create", ".write_text", ".write_bytes", ".put_object", ".upload_file", ".hset",
               ".lpush", ".rpush")
HTTP_LIBS = ("requests", "httpx", "aiohttp", "urllib")
UNTRUSTED_CALLS = ("BeautifulSoup", "trafilatura", "playwright", "selenium", "imaplib", "PyPDF", "pypdf", "fitz",
                   "docx.Document", "readability", "feedparser", "WebBaseLoader", "TavilySearch", "DuckDuckGo", "SerpAPI")


def _finish(found: set[str], name: str) -> list[str]:
    n = snake(name)
    tokens = [t for t in n.split("_") if t]
    verb = tokens[0] if tokens else ""
    writes = verb in VERB_WRITE or verb in VERB_DESTRUCTIVE
    # an HTTP POST is a write, unless the tool only looks something up (search APIs often take POST bodies)
    if HTTP_WRITE in found:
        found.discard(HTTP_WRITE)
        if verb not in VERB_READ:
            found.add("writes data")
    # outside text a prompt injection could arrive through (a tool that sends an email doesn't read one)
    if not writes and UNTRUSTED_NOUN.search(n) and ("external call" in found or re.search(r"(^|_)(url|web|page|scrape|crawl|browse)($|_)", n)):
        found.add("reads untrusted text")
    if SENDING.search(n):
        found.add("external call")
    # business actions that can't be undone (refund, cancel, send, delete...) are destructive even when the code only
    # runs an UPDATE
    if verb in VERB_DESTRUCTIVE or NOUN_DESTRUCTIVE & set(tokens):
        found.add("destructive")
    elif not found & {"destructive", "writes data"} and verb in VERB_WRITE and not found & {"read-only"}:
        found.add("writes data")
    if "destructive" in found:
        found.add("writes data")
    if found & {"destructive", "writes data"}:
        found.discard("read-only")
    elif not found - {"external call", "reads untrusted text"} and (verb in VERB_READ or found):
        found.add("read-only")
    return [e for e in ORDER if e in found]


# Built-in tools of agent SDKs (Claude Agent SDK / Claude Code), which have no code in the repository
BUILTIN_EFFECTS: dict[str, list[str]] = {
    "Read": ["read-only", "reads untrusted text"], "Grep": ["read-only", "reads untrusted text"], "Glob": ["read-only"],
    "LS": ["read-only"], "Bash": ["destructive", "writes data"], "Write": ["writes data"], "Edit": ["writes data"],
    "MultiEdit": ["writes data"], "NotebookEdit": ["writes data"], "WebFetch": ["external call", "reads untrusted text", "read-only"],
    "WebSearch": ["external call", "reads untrusted text", "read-only"], "Task": [], "TodoWrite": [],
}


def py_effects(fn: ast.AST | None, mod: "PyModule", name: str) -> list[str]:
    """Effects of a function body (or any block, e.g. one `if name == ...` branch of an MCP call handler)."""
    found: set[str] = set()
    if fn is None:
        return _finish(found, name)
    args = getattr(fn, "args", None)
    params = {a.arg for a in args.args + args.kwonlyargs} if isinstance(args, ast.arguments) else {"arguments", "args", "url"}
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            s = node.value
            if SQL_DESTRUCTIVE.search(s):
                found.add("destructive")
            elif SQL_WRITE.search(s):
                found.add("writes data")
            elif SQL_READ.search(s):
                found.add("read-only")
        elif isinstance(node, ast.Call):
            q = mod.qual(node.func) or ""
            src = q.lstrip("$")
            top = src.split(".")[0]
            vt = mod.var_type(q) or ""
            http = top in HTTP_LIBS or vt.split(".")[0] in HTTP_LIBS or src.endswith("urlopen")
            last = src.rsplit(".", 1)[-1]
            if http and last in ("post", "put", "patch"):
                found |= {HTTP_WRITE, "external call"}
            elif http and last == "delete":
                found |= {"destructive", "external call"}
            elif http and last in ("get", "request", "stream", "urlopen", "head"):
                found.add("external call")
                url = node.args[0] if node.args else None
                # fetches a URL the model chose (the whole URL is an argument, not just a value inside a fixed URL)
                if isinstance(url, ast.Name) and url.id in params or url is not None and any(
                        (isinstance(n, ast.Name) and n.id in params and re.search(r"url|uri|link|href|address", n.id, re.I))
                        or (isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in ("url", "uri", "link", "href"))
                        for n in ast.walk(url)):
                    found.add("reads untrusted text")
            if any(src.endswith(c.lstrip(".")) if c.startswith(".") else c in src for c in DESTRUCTIVE_CALLS):
                found.add("destructive")
            elif any(src.endswith(c.lstrip(".")) for c in WRITE_CALLS) and not src.startswith(("list.", "set.")):
                if last not in ("add",) or vt or "session" in src.lower() or "db" in src.lower():
                    found.add("writes data")
            if src.endswith(".delete") and not http:
                found.add("destructive")
            if any(u in src for u in UNTRUSTED_CALLS):
                found |= {"reads untrusted text", "external call"} if "Search" in src or "Loader" in src else {"reads untrusted text"}
            if src in ("open",) and len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and str(node.args[1].value)[:1] in ("w", "a"):
                found.add("writes data")
            if src in ("open",) and node.args and any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(node.args[0])):
                found.add("reads untrusted text")
    return _finish(found, name)


def text_effects(body: str, name: str) -> list[str]:
    """Same rules on raw source text (TypeScript, Go, Java)."""
    found: set[str] = set()
    if SQL_DESTRUCTIVE.search(body):
        found.add("destructive")
    elif SQL_WRITE.search(body):
        found.add("writes data")
    elif SQL_READ.search(body):
        found.add("read-only")
    if re.search(r"method:\s*['\"](POST|PUT|PATCH)['\"]|\.(post|put|patch)\(|http\.Post|HttpMethod\.POST|\.Post\(", body):
        found |= {HTTP_WRITE, "external call"}
    if re.search(r"method:\s*['\"]DELETE['\"]|axios\.delete|\.delete\(|DELETE\b", body):
        found.add("destructive")
    if re.search(r"\bfetch\(|axios\.|http\.(Get|Post|NewRequest)|[Cc]lient\w*\.(Get|Do|Post)\(|HttpClient|RestTemplate|"
                 r"RestClient|restClient|WebClient|webClient|\.retrieve\(\)|octokit|Octokit|\bgot\(|\bky\.|https?://|"
                 r"\b(stripe|twilio|sendgrid|resend|postmark|mailgun|slack|hubspot|shopify|zendesk|github|gh)\.\w+", body):
        found.add("external call")
    if re.search(r"\.(create|update|upsert|insert|save)\(|writeFile|fs\.write|\.Exec\(|\.persist\(", body):
        found.add("writes data")
    if re.search(r"\.(delete|deleteMany|destroy|remove)\(|unlink|rmSync|rm\(|exec\(|spawn\(|sendMail|\.send\(", body):
        found.add("destructive")
    return _finish(found, name)


def merge_effects(*lists: Any) -> list[str]:
    s: set[str] = set()
    for lst in lists:
        s |= set(lst or [])
    return [e for e in ORDER if e in s]
