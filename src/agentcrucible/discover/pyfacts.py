"""Python detectors: read each module with `ast` (never import or run it) and emit facts with evidence.

Imports are resolved, so `from langgraph.prebuilt import create_react_agent as cra` and `import agents as oa` are
recognised the same way. A framework is matched by its top-level package and the called name; a generic fallback
catches any model call or agent constructor that takes `tools=` in a module that uses an LLM library.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .effects import py_effects
from .scan import Inventory, SourceFile, redact
from .schema import Evidence, Fact

LLM_PACKAGES = {"openai", "anthropic", "litellm", "langchain", "langchain_core", "langchain_openai", "langchain_anthropic",
                "langchain_community", "langgraph", "agents", "crewai", "pydantic_ai", "llama_index", "autogen",
                "autogen_agentchat", "google", "dspy", "smolagents", "semantic_kernel", "claude_agent_sdk", "mistralai",
                "cohere", "groq", "ollama", "instructor", "strands", "haystack", "mcp", "fastmcp"}

# (top-level package, called name) -> (framework, role)
AGENT_CTORS: dict[tuple[str, str], tuple[str, str]] = {
    ("langgraph", "StateGraph"): ("langgraph", "graph"),
    ("langgraph", "create_react_agent"): ("langgraph", "react"),
    ("langchain", "create_agent"): ("langchain", "create"),
    ("langchain", "AgentExecutor"): ("langchain", "executor"),
    ("langchain", "create_tool_calling_agent"): ("langchain", "create"),
    ("langchain", "create_openai_tools_agent"): ("langchain", "create"),
    ("langchain", "create_openai_functions_agent"): ("langchain", "create"),
    ("langchain", "create_react_agent"): ("langchain", "create"),
    ("langchain", "create_structured_chat_agent"): ("langchain", "create"),
    ("agents", "Agent"): ("openai-agents", "agent"),
    ("crewai", "Agent"): ("crewai", "agent"),
    ("crewai", "Crew"): ("crewai", "crew"),
    ("pydantic_ai", "Agent"): ("pydantic-ai", "agent"),
    ("llama_index", "FunctionAgent"): ("llamaindex", "agent"),
    ("llama_index", "ReActAgent"): ("llamaindex", "agent"),
    ("llama_index", "AgentWorkflow"): ("llamaindex", "workflow"),
    ("llama_index", "from_tools"): ("llamaindex", "agent"),
    ("llama_index", "OpenAIAgent"): ("llamaindex", "agent"),
    ("claude_agent_sdk", "ClaudeAgentOptions"): ("claude-agent-sdk", "options"),
    ("autogen_agentchat", "AssistantAgent"): ("autogen", "agent"),
    ("autogen", "AssistantAgent"): ("autogen", "agent"),
    ("autogen", "ConversableAgent"): ("autogen", "agent"),
    ("google", "LlmAgent"): ("google-adk", "agent"),
    ("google", "Agent"): ("google-adk", "agent"),
    ("dspy", "ReAct"): ("dspy", "agent"),
    ("smolagents", "CodeAgent"): ("smolagents", "agent"),
    ("smolagents", "ToolCallingAgent"): ("smolagents", "agent"),
    ("semantic_kernel", "ChatCompletionAgent"): ("semantic-kernel", "agent"),
    ("strands", "Agent"): ("strands", "agent"),
}
TOOL_DECORATORS: dict[tuple[str, str], str] = {
    ("langchain_core", "tool"): "langchain", ("langchain", "tool"): "langchain",
    ("agents", "function_tool"): "openai-agents", ("crewai", "tool"): "crewai",
    ("claude_agent_sdk", "tool"): "claude-agent-sdk", ("semantic_kernel", "kernel_function"): "semantic-kernel",
    ("smolagents", "tool"): "smolagents", ("strands", "tool"): "strands",
}
RAW_CALL_TAILS = ("chat.completions.create", "chat.completions.parse", "beta.chat.completions.parse",
                  "responses.create", "responses.parse", "messages.create", "messages.stream", "models.generate_content")
LLM_CLIENTS = {("openai", "OpenAI"), ("openai", "AsyncOpenAI"), ("openai", "AzureOpenAI"), ("openai", "AsyncAzureOpenAI"),
               ("anthropic", "Anthropic"), ("anthropic", "AsyncAnthropic"), ("google", "Client"), ("mistralai", "Mistral"),
               ("groq", "Groq"), ("ollama", "Client")}
CHAT_MODELS = ("ChatOpenAI", "AzureChatOpenAI", "ChatAnthropic", "ChatOllama", "ChatGoogleGenerativeAI", "ChatBedrock",
               "ChatGroq", "ChatMistralAI", "OpenAIModel", "AnthropicModel", "OpenAIChatCompletionClient", "LLM", "OpenAI",
               "Anthropic", "LiteLlm", "LiteLLMModel", "OpenAIServerModel")
VECTOR_PACKAGES = {"chromadb": "chroma", "pinecone": "pinecone", "qdrant_client": "qdrant", "weaviate": "weaviate",
                   "faiss": "faiss", "pgvector": "pgvector", "lancedb": "lancedb", "langchain_chroma": "chroma",
                   "langchain_pinecone": "pinecone", "langchain_qdrant": "qdrant", "pymilvus": "milvus", "elasticsearch": "elasticsearch",
                   "opensearchpy": "opensearch", "redisvl": "redis"}
PROMPT_KWARGS = ("instructions", "system_prompt", "system", "instruction", "system_message", "backstory", "prompt")
SAAS_SDKS = {"stripe": "stripe", "twilio": "twilio", "sendgrid": "sendgrid", "slack_sdk": "slack", "boto3": "aws",
             "hubspot": "hubspot", "github": "github", "jira": "jira", "notion_client": "notion", "shopify": "shopify",
             "salesforce": "salesforce", "simple_salesforce": "salesforce", "zendesk": "zendesk", "resend": "resend"}


def module_name(rel: str) -> str:
    parts = rel[:-3].split("/") if rel.endswith(".py") else rel.split("/")
    if parts and parts[0] in ("src", "lib") and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


@dataclass
class Scope:
    """What a function (or the module) contains, for linking agents to entry points."""
    name: str
    node: ast.AST
    names_used: set[str] = field(default_factory=set)


class PyModule:
    def __init__(self, sf: SourceFile, tree: ast.Module):
        self.sf = sf
        self.tree = tree
        self.module = module_name(sf.rel)
        self.aliases: dict[str, str] = {}  # local name -> dotted import path
        self.consts: dict[str, ast.AST] = {}  # module-level NAME = value
        self.var_types: dict[str, str] = {}  # var -> dotted constructor it was assigned from
        self.functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.parents: dict[ast.AST, ast.AST] = {}
        self.top_packages: set[str] = set()
        self.local_llm: set[str] = set()  # packages in this repo that wrap an LLM library (set by detect_python)
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                self.parents[child] = node
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
                    self.top_packages.add(a.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                mod = ("." * node.level) + (node.module or "")
                if node.module:
                    self.top_packages.add(node.module.split(".")[0])
                for a in node.names:
                    self.aliases[a.asname or a.name] = f"{mod}.{a.name}" if mod else a.name
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, node)
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                self.consts[node.targets[0].id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self.consts[node.target.id] = node.value
        for node in ast.walk(tree):
            target, value = None, None
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            elif isinstance(node, ast.withitem) and isinstance(node.optional_vars, ast.Name):
                target, value = node.optional_vars.id, node.context_expr
            if target and isinstance(value, ast.Await):
                value = value.value
            if target and isinstance(value, ast.Call):
                q = self.qual(value.func)
                if q:
                    self.var_types.setdefault(target, q)

    # ---------------------------------------------------------------- resolution helpers

    @property
    def llm_module(self) -> bool:
        return bool(self.top_packages & (LLM_PACKAGES | self.local_llm))

    def qual(self, node: ast.AST) -> str | None:
        """Dotted name of an expression: imports resolved, local variables shown as `$var`."""
        parts: list[str] = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Call):  # e.g. OpenAI().chat.completions.create
            inner = self.qual(node.func)
            return ".".join([inner, *reversed(parts)]) if inner else None
        if not isinstance(node, ast.Name):
            return None
        base = self.aliases.get(node.id)
        if base is None:
            base = f"${node.id}"
        return ".".join([base, *reversed(parts)])

    def var_type(self, q: str) -> str | None:
        """For `$client.chat.completions.create`, the constructor `client` was built with."""
        if q.startswith("$"):
            var = q[1:].split(".", 1)[0]
            return self.var_types.get(var)
        return None

    @staticmethod
    def sig(q: str | None) -> tuple[str, str]:
        if not q:
            return "", ""
        parts = q.lstrip(".").split(".")
        return parts[0], parts[-1]

    def line(self, node: ast.AST) -> int:
        return getattr(node, "lineno", 1)

    def ev(self, node: ast.AST, after: int = 2) -> Evidence:
        ln = self.line(node)
        return Evidence(file=self.sf.rel, line=ln, snippet=self.sf.snippet(ln, after=after))

    def enclosing_function(self, node: ast.AST) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def enclosing_class(self, node: ast.AST) -> ast.ClassDef | None:
        while node in self.parents:
            node = self.parents[node]
            if isinstance(node, ast.ClassDef):
                return node
        return None

    def assigned_name(self, call: ast.AST) -> str | None:
        """`x = Call(...)` -> "x"; `self.x = ...` -> "x"."""
        p = self.parents.get(call)
        if isinstance(p, ast.Await):
            call, p = p, self.parents.get(p)
        if isinstance(p, ast.Assign) and len(p.targets) == 1:
            t = p.targets[0]
            if isinstance(t, ast.Name):
                return t.id
            if isinstance(t, ast.Attribute):
                return t.attr
        if isinstance(p, ast.AnnAssign) and isinstance(p.target, ast.Name):
            return p.target.id
        if isinstance(p, ast.Return):
            fn = self.enclosing_function(call)
            return fn.name if fn else None
        return None

    @staticmethod
    def kw(call: ast.Call, *names: str) -> ast.AST | None:
        for k in call.keywords:
            if k.arg in names:
                return k.value
        return None

    @staticmethod
    def arg(call: ast.Call, i: int) -> ast.AST | None:
        return call.args[i] if len(call.args) > i else None

    def resolve(self, node: ast.AST | None) -> ast.AST | None:
        """Follow a module-level constant name to its value."""
        seen = 0
        while isinstance(node, ast.Name) and node.id in self.consts and seen < 5:
            node = self.consts[node.id]
            seen += 1
        return node

    def string(self, node: ast.AST | None) -> str | None:
        node = self.resolve(node)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "{…}" for v in node.values)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = self.string(node.left), self.string(node.right)
            if a is not None or b is not None:
                return (a or "") + (b or "")
        return None

    def env_name(self, node: ast.AST | None) -> str | None:
        """os.environ["X"], os.getenv("X"), os.environ.get("X", ...), settings.X."""
        node = self.resolve(node)
        if isinstance(node, ast.Subscript):
            q = self.qual(node.value) or ""
            if q.endswith("environ"):
                return self.string(node.slice)
        if isinstance(node, ast.Call):
            q = self.qual(node.func) or ""
            if q.endswith(("getenv", "environ.get")) and node.args:
                return self.string(node.args[0])
            if q.endswith(("os.environ.setdefault",)) and node.args:
                return self.string(node.args[0])
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("settings", "config", "cfg", "SETTINGS", "CONFIG"):
            return node.attr.upper()
        return None

    def file_ref(self, node: ast.AST | None) -> str | None:
        """Path("prompts/x.md").read_text() / open("x").read() -> "prompts/x.md"."""
        node = self.resolve(node)
        if node is None:
            return None
        consts = [n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        parts = [n.value for n in sorted(consts, key=lambda c: (getattr(c, "lineno", 0), getattr(c, "col_offset", 0)))]
        for i, v in enumerate(parts):
            if re.search(r"\.(md|txt|prompt|prompty|j2|jinja2?|ya?ml)$", v):
                # Path(__file__).parent / "prompts" / "support.md": keep the folder segments before the file name
                segs = [p for p in parts[:i] if re.fullmatch(r"[\w.\-/]+", p) and p not in ("utf-8", "utf8", "r")]
                return "/".join([*segs, v]) if not v.startswith(("/", "./")) else v
        return None

    def list_items(self, node: ast.AST | None) -> list[ast.AST]:
        node = self.resolve(node)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            out: list[ast.AST] = []
            for e in node.elts:
                if isinstance(e, ast.Starred):
                    out += self.list_items(e.value)
                else:
                    out.append(e)
            return out
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.list_items(node.left) + self.list_items(node.right)
        if isinstance(node, ast.Dict):  # {"name": tool, ...}
            return [v for v in node.values if v is not None]
        if isinstance(node, ast.Call) and node.args:  # list(...), ToolNode(tools)
            return self.list_items(node.args[0])
        if isinstance(node, ast.Name):  # a local variable: find its assignment in the same function or module
            for n in ast.walk(self.tree):
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == node.id for t in n.targets):
                    items = self.list_items(n.value)
                    if items:
                        return items
        return []


def _first_sentence(text: str | None, limit: int = 220) -> str:
    if not text:
        return ""
    t = " ".join(text.strip().split())
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m else t)[:limit]


class PyDetector:
    """Runs every Python rule over one module and appends facts."""

    def __init__(self, mod: PyModule, add: Callable[[Fact], str]):
        self.m = mod
        self.add = add
        self.tool_funcs: dict[str, dict[str, Any]] = {}  # function name -> tool attrs (decorated tools)

    # ------------------------------------------------------------ helpers

    def _fact(self, fact_kind: str, fact_name: str, framework: str, at: ast.AST, /, **attrs: Any) -> str:
        return self.add(Fact(kind=fact_kind, name=fact_name, framework=framework, evidence=[self.m.ev(at)],  # type: ignore[arg-type]
                             attrs={"module": self.m.module, "file": self.m.sf.rel, "line": self.m.line(at), **attrs}))

    def _model(self, node: ast.AST | None) -> dict[str, Any]:
        """A model reference: literal, env var, or a chat-model object's `model=`."""
        node = self.m.resolve(node)
        if node is None:
            return {}
        if (s := self.m.string(node)) is not None:
            return {"value": s}
        if env := self.m.env_name(node):
            return {"env": env}
        if isinstance(node, ast.Name) and node.id in self.m.var_types:
            # llm = ChatOpenAI(model="gpt-4o"); agent(llm=llm)
            for n in ast.walk(self.m.tree):
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == node.id for t in n.targets) and isinstance(n.value, ast.Call):
                    return self._model(self.m.kw(n.value, "model", "model_name", "model_id", "deployment_name") or self.m.arg(n.value, 0))
        if isinstance(node, ast.Call):
            q = self.m.qual(node.func) or ""
            if q.rsplit(".", 1)[-1] in CHAT_MODELS or "Chat" in q or "Model" in q or q.endswith("init_chat_model"):
                return self._model(self.m.kw(node, "model", "model_name", "model_id", "deployment_name") or self.m.arg(node, 0))
        return {}

    def _prompt(self, call: ast.Call) -> dict[str, Any]:
        for k in PROMPT_KWARGS:
            v = self.m.kw(call, k)
            if v is None:
                continue
            if f := self.m.file_ref(v):
                return {"file": f}
            if (s := self.m.string(v)) is not None:
                return {"text": redact(s)[:400]}
            if env := self.m.env_name(v):
                return {"env": env}
            if isinstance(v, ast.Name):
                return {"ref": v.id}
        # messages=[{"role": "system", ...}, ...], possibly built in a local variable first
        for e in self.m.list_items(self.m.kw(call, "messages", "input")):
            if not isinstance(e, ast.Dict):
                continue
            d = {self.m.string(k): v for k, v in zip(e.keys, e.values, strict=False) if k is not None}
            if self.m.string(d.get("role")) in ("system", "developer"):
                c = d.get("content")
                if f := self.m.file_ref(c):
                    return {"file": f}
                if (s := self.m.string(c)) is not None:
                    return {"text": redact(s)[:400]}
                if env := self.m.env_name(c):
                    return {"env": env}
                if isinstance(c, ast.Name):
                    return {"ref": c.id}
        return {}

    def _tool_names(self, node: ast.AST | None) -> list[str]:
        names: list[str] = []
        for e in self.m.list_items(node):
            n = self._tool_name(e)
            if n and n not in names:
                names.append(n)
        return names

    def _tool_refs(self, node: ast.AST | None) -> dict[str, str]:
        """Tool names that are imports or local functions: name -> dotted import path (or `.:<function>` locally)."""
        out: dict[str, str] = {}
        for e in self.m.list_items(node):
            if isinstance(e, ast.Name):
                if e.id in self.m.aliases:
                    out[e.id] = self.m.aliases[e.id]
                elif e.id in self.m.functions and e.id not in self.tool_funcs:
                    out[e.id] = f"{self.m.module}.{e.id}"
        return out

    def _tool_name(self, e: ast.AST) -> str | None:
        e = self.m.resolve(e) if isinstance(e, ast.Name) and e.id in self.m.consts and not isinstance(self.m.consts[e.id], ast.Call) else e
        if isinstance(e, ast.Name):
            if e.id in self.tool_funcs:
                return self.tool_funcs[e.id]["name"]
            # search_tool = FunctionTool.from_defaults(fn=search_docs): the tool is search_docs
            for n in ast.walk(self.m.tree):
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == e.id for t in n.targets) \
                        and isinstance(n.value, ast.Call):
                    q = self.m.qual(n.value.func) or ""
                    if q.endswith(("from_defaults", "from_function", "FunctionTool", "StructuredTool", ".Tool")):
                        return self._tool_name(n.value) or e.id
            return e.id
        if isinstance(e, ast.Attribute):
            return e.attr
        if isinstance(e, ast.Dict):
            d = {self.m.string(k): v for k, v in zip(e.keys, e.values, strict=False) if k is not None}
            if "function" in d and isinstance(d["function"], ast.Dict):
                fd = {self.m.string(k): v for k, v in zip(d["function"].keys, d["function"].values, strict=False) if k is not None}
                return self.m.string(fd.get("name"))
            return self.m.string(d.get("name"))
        if isinstance(e, ast.Call):
            q = self.m.qual(e.func) or ""
            if q.endswith(("from_defaults", "from_function", "Tool", "FunctionTool")):
                name = self.m.string(self.m.kw(e, "name"))
                fn = self.m.kw(e, "fn", "func", "function") or self.m.arg(e, 0)
                return name or (fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None)
            if q.endswith(("ToolNode",)):
                return None
            return q.rsplit(".", 1)[-1]  # a built-in tool class such as TavilySearchResults
        return None

    def _func_params(self, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
        out: dict[str, str] = {}
        for a in fn.args.args + fn.args.kwonlyargs:
            if a.arg in ("self", "cls", "ctx", "context", "run_context", "wrapper"):
                continue
            out[a.arg] = ast.unparse(a.annotation) if a.annotation is not None else "any"
        return out

    # ------------------------------------------------------------ the rules

    def run(self) -> None:
        self._decorated_tools()
        self._tool_objects()
        self._mcp_servers()
        for node in ast.walk(self.m.tree):
            if isinstance(node, ast.Call):
                self._call(node)
        self._dispatch_tables()
        self._entrypoints()
        self._orm_models()
        self._settings_env()
        self._imports_deps()

    def _decorated_tools(self) -> None:
        for name, fn in self.m.functions.items():
            for dec in fn.decorator_list:
                call = dec if isinstance(dec, ast.Call) else None
                q = self.m.qual(dec.func if call else dec) or ""
                top, last = self.m.sig(q)
                framework = TOOL_DECORATORS.get((top, last))
                vt = self.m.var_type(q) or ""
                if framework is None and last in ("tool", "tool_plain") and self.m.sig(vt)[0] == "pydantic_ai":
                    framework = "pydantic-ai"
                if framework is None and last in ("tool",) and self.m.sig(vt)[1] in ("FastMCP",):
                    continue  # MCP tools are handled with their server
                if framework is None:
                    continue
                tname = (self.m.string(self.m.arg(call, 0)) if call and framework != "pydantic-ai" else None) \
                    or (self.m.string(self.m.kw(call, "name", "name_override")) if call else None) or name
                desc = self.m.string(self.m.kw(call, "description", "description_override")) if call else None
                attrs = {"function": name, "params": self._func_params(fn), "description": desc or _first_sentence(ast.get_docstring(fn)),
                         "effects": py_effects(fn, self.m, tname)}
                if framework == "pydantic-ai":
                    attrs["agent_var"] = q[1:].split(".", 1)[0]
                self.tool_funcs[name] = {"name": tname, **attrs}
                self._fact("tool", tname, framework, fn, **attrs)

    def _tool_objects(self) -> None:
        """search_tool = FunctionTool.from_defaults(fn=search_docs) at module level: a tool other modules import."""
        for var, value in self.m.consts.items():
            if not isinstance(value, ast.Call):
                continue
            q = self.m.qual(value.func) or ""
            if not q.endswith(("from_defaults", "from_function", "FunctionTool", "StructuredTool")):
                continue
            tname = self._tool_name(value)
            fn_node = self.m.kw(value, "fn", "func", "function") or self.m.arg(value, 0)
            fn = self.m.functions.get(fn_node.id) if isinstance(fn_node, ast.Name) else None
            if not tname:
                continue
            self.tool_funcs[var] = {"name": tname}
            self._fact("tool", tname, "llamaindex" if "llama_index" in q else "langchain", value, var=var,
                       function=fn.name if fn else None, params=self._func_params(fn) if fn else {},
                       description=self.m.string(self.m.kw(value, "description")) or (_first_sentence(ast.get_docstring(fn)) if fn else ""),
                       effects=py_effects(fn, self.m, tname) if fn else [],
                       import_ref=self.m.qual(fn_node).lstrip("$") if fn is None and isinstance(fn_node, ast.Attribute) else None)

    def _mcp_servers(self) -> None:
        for node in ast.walk(self.m.tree):
            if not isinstance(node, ast.Call):
                continue
            q = self.m.qual(node.func) or ""
            top, last = self.m.sig(q)
            if (top in ("mcp", "fastmcp") and last == "FastMCP") or (top == "mcp" and last == "Server" and "lowlevel" in q or q.endswith("mcp.server.Server")):
                var = self.m.assigned_name(node) or "mcp"
                sname = self.m.string(self.m.arg(node, 0)) or self.m.string(self.m.kw(node, "name")) or var
                tools: list[dict[str, Any]] = []
                for name, fn in self.m.functions.items():
                    for dec in fn.decorator_list:
                        dq = self.m.qual(dec.func if isinstance(dec, ast.Call) else dec) or ""
                        if dq in (f"${var}.tool", f"${var}.tool()"):
                            tname = (self.m.string(self.m.kw(dec, "name")) if isinstance(dec, ast.Call) else None) or name
                            desc = (self.m.string(self.m.kw(dec, "description")) if isinstance(dec, ast.Call) else None) or _first_sentence(ast.get_docstring(fn))
                            tools.append({"name": tname, "description": desc, "params": self._func_params(fn),
                                          "effects": py_effects(fn, self.m, tname), "line": fn.lineno})
                if last == "Server":  # low-level server: Tool(name="...") objects returned from list_tools
                    branches = self._call_tool_branches(var)
                    for n in ast.walk(self.m.tree):
                        if isinstance(n, ast.Call) and (self.m.qual(n.func) or "").endswith("Tool") and self.m.kw(n, "name") is not None:
                            tn = self.m.string(self.m.kw(n, "name"))
                            if tn:
                                tools.append({"name": tn, "description": self.m.string(self.m.kw(n, "description")) or "",
                                              "params": {}, "effects": py_effects(branches.get(tn), self.m, tn), "line": n.lineno})
                has_main = any(isinstance(n, ast.If) and "__main__" in ast.unparse(n.test) for n in self.m.tree.body)
                self._fact("mcp_server", sname, "mcp", node, var=var, tools=tools,
                           command=f"python {self.m.sf.rel}" if has_main else None)

    def _call_tool_branches(self, var: str) -> dict[str, ast.AST]:
        """`if name == "purge_notes": ...` blocks inside the server's @server.call_tool() handler."""
        out: dict[str, ast.AST] = {}
        for fn in self.m.functions.values():
            decs = [self.m.qual(d.func if isinstance(d, ast.Call) else d) or "" for d in fn.decorator_list]
            if not any(d.endswith(".call_tool") for d in decs):
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and len(n.test.comparators) == 1:
                    for side in (n.test.left, n.test.comparators[0]):
                        tn = self.m.string(side)
                        if tn:
                            out[tn] = ast.Module(body=n.body, type_ignores=[])
                elif isinstance(n, ast.Dict):  # HANDLERS = {"name": handler} dispatch
                    for k, v in zip(n.keys, n.values, strict=False):
                        tn = self.m.string(k) if k is not None else None
                        if tn and isinstance(v, ast.Name) and v.id in self.m.functions:
                            out[tn] = self.m.functions[v.id]
        return out

    def _call(self, call: ast.Call) -> None:
        q = self.m.qual(call.func) or ""
        top, last = self.m.sig(q)
        two = ".".join(q.split(".")[-2:])
        key = (top, last if last != "from_tools" else "from_tools")
        role = AGENT_CTORS.get(key) or AGENT_CTORS.get((top, two))
        if role is None and top == "langchain_core" and last == "tool":
            return
        if role:
            self._framework_agent(call, q, *role)
            return
        vt = self.m.var_type(q) or ""
        # graph wiring: G.add_node("name", fn_or_agent)
        if last == "add_node" and self.m.sig(vt) == ("langgraph", "StateGraph"):
            gvar = q[1:].split(".", 1)[0]
            node_name = self.m.string(self.m.arg(call, 0))
            target = self.m.arg(call, 1) if len(call.args) > 1 else self.m.arg(call, 0)
            tools = []
            if isinstance(target, ast.Call) and (self.m.qual(target.func) or "").endswith("ToolNode"):
                tools = self._tool_names(self.m.arg(target, 0))
            self._fact("subagent_edge", node_name or "node", "langgraph", call, parent_var=gvar,
                       child=target.id if isinstance(target, ast.Name) else None, node=node_name, tools=tools)
            return
        if last == "compile" and self.m.sig(vt) == ("langgraph", "StateGraph"):
            self._fact("subagent_edge", "compile", "langgraph", call, parent_var=q[1:].split(".", 1)[0],
                       compiled_as=self.m.assigned_name(call), kind="compile")
            return
        # MCP clients
        if last in ("stdio_client", "streamablehttp_client", "streamable_http_client", "sse_client", "MultiServerMCPClient") and top in ("mcp", "langchain_mcp_adapters", "fastmcp"):
            self._mcp_client(call, last)
            return
        if last == "StdioServerParameters" and top == "mcp":
            return
        if top == "claude_agent_sdk" and last == "create_sdk_mcp_server":
            sname = self.m.string(self.m.kw(call, "name")) or self.m.string(self.m.arg(call, 0)) or self.m.assigned_name(call) or "sdk"
            tools = [{"name": n} for n in self._tool_names(self.m.kw(call, "tools"))]
            self._fact("mcp_server", sname, "claude-agent-sdk", call, var=self.m.assigned_name(call), tools=tools,
                       command=None, sdk=True)
            return
        # raw LLM clients and tool-calling calls
        if (top, last) in LLM_CLIENTS or (top == "google" and q.endswith("genai.Client")):
            base = self.m.kw(call, "base_url", "azure_endpoint", "api_base")
            key = self.m.kw(call, "api_key")
            hard_base = self.m.string(base) if base is not None else None
            self._fact("llm_client", self.m.assigned_name(call) or last, top, call, provider=top,
                       hardcoded_base_url=hard_base if hard_base and hard_base.startswith("http") else None,
                       base_url_env=self.m.env_name(base) if base is not None else None,
                       hardcoded_key=bool(self.m.string(key)) if key is not None else False)
            return
        if any(q.endswith(t) for t in RAW_CALL_TAILS) or q in ("litellm.completion", "litellm.acompletion"):
            client_type = vt or q
            provider = self.m.sig(client_type)[0] if client_type else ""
            if not (provider in ("openai", "anthropic", "google", "litellm", "mistralai", "groq", "ollama") or self.m.llm_module):
                return
            tools_node = self.m.kw(call, "tools", "functions")
            enclosing = self.m.enclosing_function(call)
            params = {a.arg for a in enclosing.args.args + enclosing.args.kwonlyargs} if enclosing is not None else set()
            if tools_node is not None and any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(tools_node)):
                return  # e.g. OpenAILLM.complete(messages, tools): a wrapper the real agent calls
            if tools_node is None:
                # still a model call: useful for the model reference, but not an agent
                self._fact("model", self._model(self.m.kw(call, "model")).get("value") or "model", provider or "generic", call,
                           **self._model(self.m.kw(call, "model")))
                return
            fn = self.m.enclosing_function(call)
            cls = self.m.enclosing_class(call)
            name = fn.name if fn else self.m.module.rsplit(".", 1)[-1]
            obj = f"{cls.name}.{fn.name}" if cls and fn else name
            self._fact("agent", name, "raw-" + (provider or "llm"), call, role="loop", object=obj, factory=False,
                       function=fn.name if fn else None, cls=cls.name if cls else None,
                       tools=self._tool_names(tools_node), tool_refs=self._tool_refs(tools_node),
                       model=self._model(self.m.kw(call, "model")), prompt=self._prompt(call),
                       description=_first_sentence(ast.get_docstring(fn)) if fn else "", confidence="medium")
            return
        # data stores and outside APIs
        self._deps_call(call, q, top, last)
        # generic fallback: anything else taking tools= in an LLM module
        if self.m.llm_module and self.m.kw(call, "tools") is not None and not q.startswith("$self") and last not in ("bind_tools", "ToolNode", "dict", "list"):
            tools = self._tool_names(self.m.kw(call, "tools"))
            if tools and last in ("create_sdk_mcp_server",):
                return
            if tools:
                var = self.m.assigned_name(call)
                fn = self.m.enclosing_function(call)
                self._fact("agent", var or (fn.name if fn else last), "generic", call, role="fallback", ctor=q,
                           object=var, factory=False, tools=tools, tool_refs=self._tool_refs(self.m.kw(call, "tools")),
                           model=self._model(self.m.kw(call, "model", "llm")),
                           prompt=self._prompt(call), confidence="low",
                           description=f"Built with {q.lstrip('$')}(…, tools=…); no detector for this framework yet.")

    def _framework_agent(self, call: ast.Call, q: str, framework: str, role: str) -> None:
        m = self.m
        var = m.assigned_name(call)
        fn = m.enclosing_function(call)
        factory = None
        p = m.parents.get(call)
        if isinstance(p, ast.Return) and fn:
            factory = fn.name
        elif fn and var:
            # `agent = X(...); return agent` inside a builder function
            if any(isinstance(n, ast.Return) and isinstance(n.value, ast.Name) and n.value.id == var for n in ast.walk(fn)):
                factory = fn.name
        cls = m.enclosing_class(call)
        attrs: dict[str, Any] = {"role": role, "object": var, "factory": factory, "ctor": q.lstrip("$"),
                                 "cls": cls.name if cls else None}
        name = m.string(m.kw(call, "name", "role")) or var or factory or q.rsplit(".", 1)[-1]
        tools_kw = m.kw(call, "tools", "functions", "allowed_tools")
        if role == "react":
            tools_kw = tools_kw or m.arg(call, 1)
            attrs["model"] = self._model(m.kw(call, "model") or m.arg(call, 0))
        elif framework == "pydantic-ai":
            attrs["model"] = self._model(m.kw(call, "model") or m.arg(call, 0))
        elif framework == "dspy":
            tools_kw = tools_kw or m.arg(call, 1)
        else:
            attrs["model"] = self._model(m.kw(call, "model", "llm", "model_client", "chat_client"))
        attrs["tools"] = self._tool_names(tools_kw)
        if framework == "claude-agent-sdk":
            allowed = [s for s in (m.string(e) for e in m.list_items(m.kw(call, "allowed_tools"))) if s]
            attrs["tools"] = [a.split("__")[-1] if a.startswith("mcp__") else a for a in allowed]
            sub = m.resolve(m.kw(call, "agents"))
            attrs["members"] = []
            if isinstance(sub, ast.Dict):
                for k, v in zip(sub.keys, sub.values, strict=False):
                    key = m.string(k) if k is not None else None
                    if not key or not isinstance(v, ast.Call):
                        continue
                    attrs["members"].append(key)
                    sub_tools = [x for x in (m.string(e) for e in m.list_items(m.kw(v, "tools"))) if x]
                    self._fact("agent", key, "claude-agent-sdk", v, role="subagent", object=None, factory=None, tools=sub_tools,
                               model=self._model(m.kw(v, "model")), prompt=self._prompt(v),
                               description=m.string(m.kw(v, "description")) or "", confidence="high")
            attrs["mcp_config"] = [m.string(k) for k in m.resolve(m.kw(call, "mcp_servers")).keys] if isinstance(m.resolve(m.kw(call, "mcp_servers")), ast.Dict) else []
            name = var or (fn.name if fn else "claude_agent")
            attrs["object"] = None
            attrs["function"] = fn.name if fn else None
        attrs["prompt"] = self._prompt(call)
        desc = m.string(m.kw(call, "description", "goal", "handoff_description"))
        if framework == "crewai" and role == "agent":
            r, g = m.string(m.kw(call, "role")), m.string(m.kw(call, "goal"))
            desc = " — ".join(x for x in (r, g) if x) or desc
            cfg = m.kw(call, "config")
            if cfg is not None:  # Agent(config=self.agents_config["researcher"])
                key = next((m.string(n.slice) for n in ast.walk(cfg) if isinstance(n, ast.Subscript)), None)
                if key:
                    name = key
                    attrs["config_key"] = key
            if cls and fn and any((m.qual(d.func if isinstance(d, ast.Call) else d) or "").endswith("agent") for d in fn.decorator_list):
                attrs["method"] = fn.name
                name = attrs.get("config_key") or fn.name
        if framework == "crewai" and role == "crew":
            attrs["members"] = [e.id if isinstance(e, ast.Name) else ast.unparse(e) for e in m.list_items(m.kw(call, "agents"))]
            name = var or (fn.name if fn else "crew")
        if role == "workflow":
            attrs["members"] = [e.id for e in m.list_items(m.kw(call, "agents")) if isinstance(e, ast.Name)]
        for k in ("handoffs", "sub_agents"):
            v = m.kw(call, k)
            if v is not None:
                attrs["members"] = [e.id if isinstance(e, ast.Name) else ast.unparse(e) for e in m.list_items(v)]
        if role == "graph":
            attrs["tools"] = []
        if role == "executor":
            wrapped = m.kw(call, "agent")
            attrs["wraps"] = wrapped.id if isinstance(wrapped, ast.Name) else None
        attrs["tool_refs"] = self._tool_refs(tools_kw)
        attrs["description"] = desc or ""
        attrs["confidence"] = "high"
        self._fact("agent", name, framework, call, **attrs)

    def _mcp_client(self, call: ast.Call, last: str) -> None:
        m = self.m
        if last == "stdio_client":
            params = m.resolve(m.arg(call, 0))
            if isinstance(params, ast.Name):
                for n in ast.walk(m.tree):
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == params.id for t in n.targets):
                        params = n.value
            cmd = None
            if isinstance(params, ast.Call):
                c = m.string(m.kw(params, "command"))
                args = [m.string(a) or "…" for a in m.list_items(m.kw(params, "args"))]
                cmd = " ".join([c or "…", *args]) if c else None
            self._fact("mcp_client", cmd or "stdio server", "mcp", call, transport="stdio", command=cmd)
        elif last == "MultiServerMCPClient":
            cfg = m.resolve(m.arg(call, 0))
            if isinstance(cfg, ast.Dict):
                for k, v in zip(cfg.keys, cfg.values, strict=False):
                    sname = m.string(k)
                    d = {m.string(kk): vv for kk, vv in zip(v.keys, v.values, strict=False) if kk is not None} if isinstance(v, ast.Dict) else {}
                    cmd = m.string(d.get("command"))
                    args = [m.string(a) or "…" for a in m.list_items(d.get("args"))]
                    self._fact("mcp_client", sname or "server", "mcp", call, name=sname, transport=m.string(d.get("transport")) or "stdio",
                               command=" ".join([cmd, *args]) if cmd else None, url=m.string(d.get("url")))
        else:
            url_node = m.arg(call, 0) or m.kw(call, "url")
            self._fact("mcp_client", m.string(url_node) or m.env_name(url_node) or "remote server", "mcp", call,
                       transport="sse" if last == "sse_client" else "http", url=m.string(url_node), url_env=m.env_name(url_node))

    def _dispatch_tables(self) -> None:
        """TOOLS = {"refund": refund_order, ...}: links tool names in a raw loop to their implementations."""
        for name, value in self.m.consts.items():
            if not isinstance(value, ast.Dict) or not value.keys:
                continue
            pairs = [(self.m.string(k), v) for k, v in zip(value.keys, value.values, strict=False) if k is not None]
            impls = [(k, v.id) for k, v in pairs if k and isinstance(v, ast.Name)
                     and (v.id in self.m.functions or v.id in self.m.aliases)]
            if len(impls) >= 1 and len(impls) == len(pairs) and len(pairs) <= 200:
                for tname, fname in impls:
                    if fname in self.tool_funcs:
                        continue
                    if fname not in self.m.functions:  # imported from another module: resolved after all files are read
                        self._fact("tool", tname, "raw", value, function=fname, dispatch=name, dispatch_module=self.m.module,
                                   import_ref=self.m.aliases[fname], params={}, description="", effects=[])
                        continue
                    fn = self.m.functions[fname]
                    self._fact("tool", tname, "raw", fn, function=fname, dispatch=name, dispatch_module=self.m.module,
                               params=self._func_params(fn), description=_first_sentence(ast.get_docstring(fn)),
                               effects=py_effects(fn, self.m, tname))
        # schema-only tools in raw tool lists: [{"type": "function", "function": {"name": ...}}]
        for name, value in self.m.consts.items():
            for e in self.m.list_items(value) if isinstance(value, (ast.List, ast.Tuple)) else []:
                if isinstance(e, ast.Dict):
                    tn = self._tool_name(e)
                    if tn:
                        d = {self.m.string(k): v for k, v in zip(e.keys, e.values, strict=False) if k is not None}
                        fd = d.get("function")
                        fdd = {self.m.string(k): v for k, v in zip(fd.keys, fd.values, strict=False) if k is not None} if isinstance(fd, ast.Dict) else d
                        params = fdd.get("parameters") or fdd.get("input_schema")
                        pnames: dict[str, str] = {}
                        if isinstance(params, ast.Dict):
                            pd = {self.m.string(k): v for k, v in zip(params.keys, params.values, strict=False) if k is not None}
                            props = pd.get("properties")
                            if isinstance(props, ast.Dict):
                                for pk, pv in zip(props.keys, props.values, strict=False):
                                    pn = self.m.string(pk)
                                    pt = None
                                    if isinstance(pv, ast.Dict):
                                        pt = self.m.string(dict(zip([self.m.string(x) for x in pv.keys], pv.values, strict=False)).get("type"))
                                    if pn:
                                        pnames[pn] = pt or "any"
                        impl = self.m.functions.get(tn)
                        self._fact("tool", tn, "raw", e, schema_list=name, params=pnames,
                                   description=self.m.string(fdd.get("description")) or "",
                                   function=tn if impl else None,
                                   import_ref=self.m.aliases.get(tn) if not impl else None,
                                   effects=py_effects(impl, self.m, tn) if impl else [])

    def _entrypoints(self) -> None:
        m = self.m
        apps = {var for var, t in m.var_types.items() if self.m.sig(t)[1] in ("FastAPI", "APIRouter", "Flask", "Blueprint", "Starlette", "Quart", "Sanic")}
        for fname, fn in m.functions.items():
            for dec in fn.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                q = m.qual(dec.func) or ""
                if not q.startswith("$"):
                    continue
                var, _, meth = q[1:].partition(".")
                if var not in apps or meth not in ("post", "get", "put", "route", "api_route", "websocket", "patch"):
                    continue
                path = m.string(m.arg(dec, 0)) or "/"
                method = "POST" if meth in ("post", "route", "api_route") else meth.upper()
                if meth == "route":
                    methods = m.kw(dec, "methods")
                    ms = [m.string(x) for x in m.list_items(methods)] if methods is not None else ["GET"]
                    method = "POST" if "POST" in ms else (ms[0] or "GET")
                used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
                body_fields = []
                for a in fn.args.args:
                    if a.annotation is not None:
                        body_fields.append(ast.unparse(a.annotation))
                app_var = var if self.m.sig(m.var_types.get(var, ""))[1] in ("FastAPI", "Flask", "Starlette", "Quart", "Sanic") else None
                self._fact("entrypoint", f"{method} {path}", "http", fn, kind="http", method=method, route=path,
                           function=fname, names_used=sorted(used), app_var=app_var or next(
                               (v for v in apps if self.m.sig(m.var_types.get(v, ""))[1] in ("FastAPI", "Flask")), None),
                           websocket=meth == "websocket", body_types=body_fields)
        for node in m.tree.body:
            if isinstance(node, ast.If) and "__main__" in ast.unparse(node.test):
                used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
                self._fact("entrypoint", f"python {m.sf.rel}", "cli", node, kind="cli", command=f"python {m.sf.rel}",
                           names_used=sorted(used))

    def _deps_call(self, call: ast.Call, q: str, top: str, last: str) -> None:
        m = self.m
        if (top, last) in {("sqlalchemy", "create_engine"), ("sqlalchemy", "create_async_engine"), ("psycopg", "connect"),
                           ("psycopg2", "connect"), ("asyncpg", "connect"), ("asyncpg", "create_pool"), ("sqlite3", "connect"),
                           ("pymongo", "MongoClient"), ("motor", "AsyncIOMotorClient"), ("redis", "Redis"), ("redis", "from_url"),
                           ("sqlmodel", "create_engine"), ("peewee", "SqliteDatabase"), ("peewee", "PostgresqlDatabase"),
                           ("databases", "Database"), ("aiosqlite", "connect")}:
            url_node = m.arg(call, 0) or m.kw(call, "url", "dsn", "database", "conninfo")
            url = m.string(url_node)
            kind = "sqlite" if top in ("sqlite3", "aiosqlite") or (url or "").startswith("sqlite") else \
                "postgres" if top in ("psycopg", "psycopg2", "asyncpg") or (url or "").startswith(("postgres", "postgresql")) else \
                "mongodb" if top in ("pymongo", "motor") else "redis" if top == "redis" else "unknown"
            env = m.env_name(url_node)
            fn = m.enclosing_function(call)
            if env is None:  # the URL arrives through a variable: look for a database setting read nearby
                for scope in ([fn] if fn else []) + [m.tree]:
                    names = [m.env_name(n) for n in ast.walk(scope) if isinstance(n, (ast.Call, ast.Subscript))]
                    env = next((x for x in names if x and re.search(r"DATABASE|(^|_)DB(_|$)|SQLITE|POSTGRES|MONGO|REDIS|DSN", x)), None)
                    if env:
                        break
            self._fact("datastore", env or kind, kind, call, kind=kind, url_env=env, url=redact(url) if url else None,
                       function=fn.name if fn else None)
            return
        if top in ("requests", "httpx", "aiohttp", "urllib") or self.m.sig(self.m.var_type(q) or "")[0] in ("httpx", "requests", "aiohttp"):
            if last in ("Client", "AsyncClient", "Session", "ClientSession"):
                base = m.kw(call, "base_url")
                if base is not None:
                    url, env = m.string(base), m.env_name(base)
                    self._fact("external_api", _host(url) or env or "api", "http", call, base_url=url, base_url_env=env)
                return
            if last in ("get", "post", "put", "patch", "delete", "request", "urlopen", "stream"):
                url_node = m.arg(call, 1) if last == "request" else m.arg(call, 0) or m.kw(call, "url")
                url = m.string(url_node)
                env = None
                if isinstance(url_node, ast.JoinedStr):
                    for v in url_node.values:
                        if isinstance(v, ast.FormattedValue):
                            env = m.env_name(v.value) or (v.value.id.upper() if isinstance(v.value, ast.Name) and v.value.id.isupper() else None)
                            if env:
                                break
                    if env is None:
                        first = url_node.values[0] if url_node.values else None
                        if isinstance(first, ast.FormattedValue) and isinstance(first.value, ast.Name) and first.value.id in m.consts:
                            env = m.env_name(m.consts[first.value.id])
                host = _host(url)
                if host or env:
                    path = re.sub(r"^(https?://[^/]+|\{…\})", "", url or "").replace("{…}", "*") or "/"
                    method = m.string(m.arg(call, 0)).upper() if last == "request" and m.string(m.arg(call, 0)) else ("GET" if last in ("get", "urlopen", "stream") else last.upper())
                    fn = m.enclosing_function(call)
                    self._fact("external_api", host or env or "api", "http", call, base_url=f"https://{host}" if host else None,
                               base_url_env=env, path=f"{method} {path}", function=fn.name if fn else None)

    def _orm_models(self) -> None:
        m = self.m
        for node in ast.walk(m.tree):
            if not isinstance(node, ast.ClassDef):
                continue
            table = None
            cols: dict[str, str] = {}
            for st in node.body:
                if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in st.targets):
                    table = m.string(st.value)
                target = st.targets[0] if isinstance(st, ast.Assign) and len(st.targets) == 1 else st.target if isinstance(st, ast.AnnAssign) else None
                value = st.value if isinstance(st, (ast.Assign, ast.AnnAssign)) else None
                if isinstance(target, ast.Name) and isinstance(value, ast.Call):
                    q = m.qual(value.func) or ""
                    if q.endswith(("Column", "mapped_column", "Field")):
                        typ = next((ast.unparse(a) for a in value.args if not isinstance(a, ast.Constant)), None)
                        ann = ast.unparse(st.annotation) if isinstance(st, ast.AnnAssign) else ""
                        cols[target.id] = _sql_type(typ or ann)
                elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and not st.target.id.startswith("_"):
                    if any(isinstance(k, ast.keyword) and k.arg == "table" for k in node.keywords):
                        cols[st.target.id] = _sql_type(ast.unparse(st.annotation))
            sqlmodel_table = any(isinstance(k, ast.keyword) and k.arg == "table" for k in node.keywords)
            if table or (sqlmodel_table and cols):
                self._fact("datastore", "orm", "orm", node, kind="unknown", table=table or node.name.lower(), columns=cols)

    def _settings_env(self) -> None:
        m = self.m
        for node in ast.walk(m.tree):
            if isinstance(node, ast.ClassDef) and any((m.qual(b) or "").endswith("BaseSettings") for b in node.bases):
                for st in node.body:
                    if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                        self._fact("env_var", st.target.id.upper(), "settings", st)
            if isinstance(node, (ast.Subscript, ast.Call)):
                env = m.env_name(node)
                if env and re.fullmatch(r"[A-Z][A-Z0-9_]{1,60}", env):
                    self._fact("env_var", env, "env", node)

    def _imports_deps(self) -> None:
        m = self.m
        for node in ast.walk(m.tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for n in names:
                    top = n.split(".")[0]
                    if top in VECTOR_PACKAGES or (n.startswith(("langchain_community.vectorstores", "llama_index.vector_stores"))):
                        kind = VECTOR_PACKAGES.get(top) or n.rsplit(".", 1)[-1]
                        self._fact("vector_store", kind, kind, node, kind=kind)
                    if top in SAAS_SDKS:
                        self._fact("external_api", SAAS_SDKS[top], "sdk", node, sdk=top)


def _host(url: str | None) -> str | None:
    if not url:
        return None
    mm = re.match(r"https?://([^/{:]+)", url)
    if not mm:
        return None
    host = mm.group(1)
    return None if host in ("localhost", "127.0.0.1", "0.0.0.0") else host


def _sql_type(t: str | None) -> str:
    t = (t or "").lower()
    if "int" in t:
        return "INTEGER"
    if any(x in t for x in ("float", "numeric", "decimal", "double", "real")):
        return "REAL"
    if "bool" in t:
        return "BOOLEAN"
    if "date" in t or "time" in t:
        return "TIMESTAMP"
    if "json" in t or "dict" in t or "list" in t:
        return "JSON"
    return "TEXT"


def detect_python(inv: Inventory, add: Callable[[Fact], str]) -> int:
    produced: list[Fact] = []

    def collect(f: Fact) -> str:
        produced.append(f)
        return add(f)

    modules: list[PyModule] = []
    for sf in inv.code("python"):
        try:
            tree = ast.parse(sf.text, filename=sf.rel)
        except (SyntaxError, ValueError):
            continue
        mod = PyModule(sf, tree)
        modules.append(mod)
    local_llm = {m.module.split(".")[0] for m in modules if m.llm_module} - {""}
    for mod in modules:
        mod.local_llm = local_llm
        PyDetector(mod, collect).run()
    _resolve_imported_tools(modules, produced)
    _function_tools(modules, produced, collect)
    return len(modules)


def _function_tools(modules: list[PyModule], facts: list[Fact], add: Callable[[Fact], str]) -> None:
    """Agents list tools by function. Decorated tools defined in another module are renamed to the name the model sees;
    plain functions (Google ADK, AutoGen, OpenAI Agents with function_tool applied elsewhere...) become tools."""
    index: dict[str, tuple[PyModule, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for mod in modules:
        for fname, fn in mod.functions.items():
            index[f"{mod.module}.{fname}"] = (mod, fn)
    decorated = {f"{f.attrs.get('module')}.{f.attrs.get('function')}": f.name for f in facts
                 if f.kind == "tool" and f.attrs.get("function") and f.attrs.get("module")}
    decorated |= {f"{f.attrs.get('module')}.{f.attrs.get('var')}": f.name for f in facts
                  if f.kind == "tool" and f.attrs.get("var") and f.attrs.get("module")}
    known = {f.name for f in facts if f.kind == "tool"} | {t.get("name") for f in facts if f.kind == "mcp_server"
                                                           for t in f.attrs.get("tools") or [] if isinstance(t, dict)}
    for f in list(facts):
        if f.kind != "agent" or not f.attrs.get("tool_refs"):
            continue
        mod_name = f.attrs.get("module", "")
        new_tools = []
        for name in f.attrs.get("tools") or []:
            ref = f.attrs["tool_refs"].get(name)
            if ref and ref.startswith("."):
                pkg = mod_name.split(".")
                level = len(ref) - len(ref.lstrip("."))
                ref = ".".join(pkg[: max(0, len(pkg) - level)] + [ref.lstrip(".")])
            hit_key = next((k for k in ([ref] if ref else []) + [k for k in decorated if ref and (k.endswith("." + ref) or ref.endswith("." + k))]
                            if k in decorated), None)
            if hit_key:
                new_tools.append(decorated[hit_key])
                continue
            new_tools.append(name)
            if not ref or name in known:
                continue
            hit = index.get(ref) or next((v for k, v in index.items() if k.endswith("." + ref) or ref.endswith("." + k)), None)
            if hit is None:
                continue
            mod, fn = hit
            params = {a.arg: ast.unparse(a.annotation) if a.annotation is not None else "any"
                      for a in fn.args.args + fn.args.kwonlyargs if a.arg not in ("self", "cls", "ctx", "context", "tool_context")}
            add(Fact(kind="tool", name=name, framework=f.framework,
                     evidence=[Evidence(file=mod.sf.rel, line=fn.lineno, snippet=mod.sf.snippet(fn.lineno))],
                     attrs={"module": mod.module, "file": mod.sf.rel, "line": fn.lineno, "function": fn.name, "params": params,
                            "description": _first_sentence(ast.get_docstring(fn)), "effects": py_effects(fn, mod, name)}))
            known.add(name)
        f.attrs["tools"] = list(dict.fromkeys(new_tools))


def _resolve_imported_tools(modules: list[PyModule], facts: list[Fact]) -> None:
    """Tools named in one module but implemented in another (`from app.tools import refund`): follow the import to the
    function, so the tool gets its real description, parameters and side effects, and adapters wrap the right module."""
    index: dict[str, tuple[PyModule, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for mod in modules:
        for fname, fn in mod.functions.items():
            index[f"{mod.module}.{fname}"] = (mod, fn)
    for f in facts:
        ref = f.attrs.get("import_ref")
        if f.kind != "tool" or not ref:
            continue
        if ref.startswith("."):  # relative import: resolve against the importing module's package
            pkg = f.attrs.get("module", "").split(".")
            level = len(ref) - len(ref.lstrip("."))
            ref = ".".join(pkg[: max(0, len(pkg) - level)] + [ref.lstrip(".")])
        hit = index.get(ref) or next((v for k, v in index.items() if k.endswith("." + ref) or ref.endswith("." + k)), None)
        if hit is None:
            continue
        mod, fn = hit
        params = {a.arg: ast.unparse(a.annotation) if a.annotation is not None else "any"
                  for a in fn.args.args + fn.args.kwonlyargs if a.arg not in ("self", "cls", "ctx", "context")}
        f.attrs.update(module=mod.module, function=fn.name, impl_file=mod.sf.rel,
                       params=f.attrs.get("params") or params,
                       description=f.attrs.get("description") or _first_sentence(ast.get_docstring(fn)),
                       effects=py_effects(fn, mod, f.name))
        f.evidence.append(Evidence(file=mod.sf.rel, line=fn.lineno, snippet=mod.sf.snippet(fn.lineno)))
