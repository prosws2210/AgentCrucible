"""TypeScript/JavaScript, Go and Java detectors (tree-sitter). Like the Python ones, they only read the code."""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator

import tree_sitter as ts
import tree_sitter_go as tsgo
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts

from .effects import text_effects
from .scan import Inventory, SourceFile, redact
from .schema import Evidence, Fact

_LANGS = {
    "typescript": ts.Language(tsts.language_typescript()),
    "tsx": ts.Language(tsts.language_tsx()),
    "javascript": ts.Language(tsjs.language()),
    "go": ts.Language(tsgo.language()),
    "java": ts.Language(tsjava.language()),
}
LLM_PKGS = ("ai", "@ai-sdk/", "openai", "@anthropic-ai/", "@mastra/", "@openai/agents", "@langchain/", "langchain",
            "@modelcontextprotocol/", "@google/genai", "@google/generative-ai", "ollama", "groq-sdk", "@mistralai/")


def _parse(sf: SourceFile) -> ts.Tree | None:
    lang = "tsx" if sf.rel.endswith(".tsx") else sf.language or ""
    language = _LANGS.get(lang)
    if language is None:
        return None
    try:
        return ts.Parser(language).parse(sf.text.encode("utf-8"))
    except Exception:  # noqa: BLE001 - a file tree-sitter can't parse is just skipped
        return None


def _walk(node: ts.Node) -> Iterator[ts.Node]:
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


class TsModule:
    def __init__(self, sf: SourceFile, tree: ts.Tree):
        self.sf = sf
        self.src = sf.text.encode("utf-8")
        self.root = tree.root_node
        self.aliases: dict[str, str] = {}
        self.var_types: dict[str, str] = {}
        self.packages: set[str] = set()
        for n in _walk(self.root):
            if n.type == "import_statement":
                srcn = n.child_by_field_name("source")
                pkg = self.string(srcn) if srcn else None
                if not pkg:
                    continue
                self.packages.add(pkg)
                for c in _walk(n):
                    if c.type == "import_specifier":
                        name = c.child_by_field_name("name")
                        alias = c.child_by_field_name("alias")
                        if name:
                            self.aliases[self.t(alias or name)] = f"{pkg}#{self.t(name)}"
                    elif c.type == "namespace_import":
                        ident = next((x for x in c.children if x.type == "identifier"), None)
                        if ident:
                            self.aliases[self.t(ident)] = f"{pkg}#*"
                    elif c.type == "import_clause":
                        ident = next((x for x in c.children if x.type == "identifier"), None)
                        if ident:
                            self.aliases[self.t(ident)] = f"{pkg}#default"
            elif n.type == "variable_declarator":
                name, value = n.child_by_field_name("name"), n.child_by_field_name("value")
                if name is None or value is None:
                    continue
                if value.type == "await_expression" and value.named_children:
                    value = value.named_children[0]
                if value.type == "call_expression" and self.t(value.child_by_field_name("function")) == "require":
                    arg = value.child_by_field_name("arguments")
                    pkg = self.string(arg.named_children[0]) if arg and arg.named_children else None
                    if pkg:
                        self.packages.add(pkg)
                        if name.type == "identifier":
                            self.aliases[self.t(name)] = f"{pkg}#default"
                        else:
                            for c in _walk(name):
                                if c.type in ("shorthand_property_identifier_pattern", "identifier"):
                                    self.aliases[self.t(c)] = f"{pkg}#{self.t(c)}"
                elif value.type in ("new_expression", "call_expression") and name.type == "identifier":
                    callee = value.child_by_field_name("constructor") or value.child_by_field_name("function")
                    q = self.qual(callee) if callee else None
                    if q:
                        self.var_types[self.t(name)] = q

    @property
    def llm_module(self) -> bool:
        return any(p == x or p.startswith(x) for p in self.packages for x in LLM_PKGS)

    def t(self, node: ts.Node | None) -> str:
        return self.src[node.start_byte:node.end_byte].decode("utf-8", "replace") if node else ""

    def line(self, node: ts.Node) -> int:
        return node.start_point[0] + 1

    def ev(self, node: ts.Node) -> Evidence:
        ln = self.line(node)
        return Evidence(file=self.sf.rel, line=ln, snippet=self.sf.snippet(ln))

    def string(self, node: ts.Node | None) -> str | None:
        if node is None:
            return None
        if node.type in ("string", "template_string"):
            s = self.t(node)
            return s[1:-1] if len(s) >= 2 else s
        return None

    def qual(self, node: ts.Node | None) -> str | None:
        if node is None:
            return None
        if node.type == "identifier":
            name = self.t(node)
            return self.aliases.get(name, f"${name}")
        if node.type == "member_expression":
            obj = self.qual(node.child_by_field_name("object"))
            prop = self.t(node.child_by_field_name("property"))
            return f"{obj}.{prop}" if obj else None
        if node.type in ("call_expression",):
            return self.qual(node.child_by_field_name("function"))
        if node.type == "this":
            return "$this"
        return None

    def obj(self, node: ts.Node | None) -> dict[str, ts.Node]:
        out: dict[str, ts.Node] = {}
        if node is None or node.type != "object":
            return out
        for c in node.named_children:
            if c.type == "pair":
                k = c.child_by_field_name("key")
                key = self.string(k) or self.t(k)
                v = c.child_by_field_name("value")
                if v is not None:
                    out[key] = v
            elif c.type == "shorthand_property_identifier":
                out[self.t(c)] = c
            elif c.type == "method_definition":
                out[self.t(c.child_by_field_name("name"))] = c
        return out

    def first_obj_arg(self, call: ts.Node) -> ts.Node | None:
        args = call.child_by_field_name("arguments")
        if args is None:
            return None
        return next((a for a in args.named_children if a.type == "object"), None)

    def arg(self, call: ts.Node, i: int) -> ts.Node | None:
        args = call.child_by_field_name("arguments")
        kids = args.named_children if args else []
        return kids[i] if len(kids) > i else None

    def resolve(self, node: ts.Node | None) -> ts.Node | None:
        """An identifier -> its `const x = ...` value in this file."""
        if node is None or node.type not in ("identifier", "shorthand_property_identifier"):
            return node
        name = self.t(node)
        for n in _walk(self.root):
            if n.type == "variable_declarator" and self.t(n.child_by_field_name("name")) == name:
                return n.child_by_field_name("value")
        return node

    def assigned_name(self, node: ts.Node) -> str | None:
        p = node.parent
        while p is not None and p.type in ("await_expression", "parenthesized_expression", "as_expression"):
            p = p.parent
        if p is not None and p.type == "variable_declarator":
            return self.t(p.child_by_field_name("name"))
        if p is not None and p.type == "pair":
            return self.string(p.child_by_field_name("key")) or self.t(p.child_by_field_name("key"))
        return None

    def enclosing_function(self, node: ts.Node) -> str | None:
        p = node.parent
        while p is not None:
            if p.type in ("function_declaration", "method_definition", "generator_function_declaration"):
                return self.t(p.child_by_field_name("name"))
            if p.type in ("arrow_function", "function_expression", "function"):
                d = p.parent
                if d is not None and d.type == "variable_declarator":
                    return self.t(d.child_by_field_name("name"))
            p = p.parent
        return None

    def exported(self, name: str | None) -> bool:
        if not name:
            return False
        cache = self.__dict__.setdefault("_exported_cache", {})  # asked once per call expression: big files have thousands
        if name not in cache:
            cache[name] = self._exported(name)
        return cache[name]

    def _exported(self, name: str) -> bool:
        return bool(re.search(rf"export\s+(default\s+)?(async\s+)?(function\*?\s+|const\s+|let\s+|class\s+){re.escape(name)}\b",
                              self.sf.text) or re.search(rf"export\s*\{{[^}}]*\b{re.escape(name)}\b", self.sf.text)
                    or re.search(rf"module\.exports\s*=.*\b{re.escape(name)}\b", self.sf.text))

    def zod_keys(self, node: ts.Node | None) -> dict[str, str]:
        node = self.resolve(node)
        if node is None:
            return {}
        if node.type == "call_expression" and self.t(node.child_by_field_name("function")).endswith("object"):
            o = self.first_obj_arg(node)
            return {k: _zod_type(self.t(v)) for k, v in self.obj(o).items()}
        if node.type == "object":  # JSON schema
            props = self.obj(node).get("properties")
            return {k: "any" for k in self.obj(props)} if props is not None else {}
        return {}


def _zod_type(src: str) -> str:
    m = re.search(r"z\.(string|number|boolean|array|object|enum|date)", src)
    return m.group(1) if m else "any"


def _pkg_is(q: str | None, pkg: str, name: str | None = None) -> bool:
    if not q or "#" not in q:
        return False
    p, _, rest = q.partition("#")
    first = rest.split(".")[0]
    return (p == pkg or p.startswith(pkg + "/")) and (name is None or first == name or rest == name)


class TsDetector:
    def __init__(self, m: TsModule, add: Callable[[Fact], str]):
        self.m = m
        self.add = add
        self.tool_vars: dict[str, str] = {}  # const refundTool = tool({...}) -> tool name
        self.tool_facts: dict[str, Fact] = {}  # const refundTool -> its fact (renamed to the key the model sees)
        self.aliases_seen: dict[str, str] = {}  # variable -> object key, for tools defined in another file

    def _fact(self, fact_kind: str, fact_name: str, framework: str, at: ts.Node, /, **attrs: Any) -> Fact:
        lang = self.m.sf.language or "typescript"
        return self._add(Fact(kind=fact_kind, name=fact_name, framework=framework, evidence=[self.m.ev(at)],  # type: ignore[arg-type]
                             attrs={"file": self.m.sf.rel, "line": self.m.line(at), "language": lang,
                                    "module": re.sub(r"\.(m|c)?[tj]sx?$", "", self.m.sf.rel), **attrs}))

    def _add(self, f: Fact) -> Fact:
        self.add(f)
        return f

    def _tool_names(self, node: ts.Node | None) -> list[str]:
        node = self.m.resolve(node)
        if node is None:
            return []
        if node.type == "object":
            pairs = self.m.obj(node)
            for key, value in pairs.items():  # the object key is the name the model sees
                var = self.m.t(value) if value.type in ("identifier", "shorthand_property_identifier") else None
                if var:
                    self.aliases_seen[var] = key
                if var and var in self.tool_facts and self.tool_facts[var].name != key:
                    self.tool_facts[var].name = key
                    self.tool_vars[var] = key
            return list(pairs)
        if node.type == "array":
            out = []
            for e in node.named_children:
                if e.type == "identifier":
                    out.append(self.tool_vars.get(self.m.t(e), self.m.t(e)))
                elif e.type == "call_expression":
                    o = self.m.first_obj_arg(e)
                    nm = self.m.string(self.m.obj(o).get("name")) if o is not None else None
                    out.append(nm or self.m.assigned_name(e) or "tool")
            return out
        return []

    def _model(self, node: ts.Node | None) -> dict[str, Any]:
        if node is None:
            return {}
        if (s := self.m.string(node)) is not None:
            return {"value": s}
        src = self.m.t(node)
        mm = re.search(r"\(\s*['\"`]([^'\"`]+)['\"`]", src)
        if mm:
            return {"value": mm.group(1)}
        env = re.search(r"process\.env\.([A-Z0-9_]+)", src)
        return {"env": env.group(1)} if env else {}

    def _prompt(self, o: dict[str, ts.Node]) -> dict[str, Any]:
        for k in ("instructions", "system", "systemPrompt", "prompt"):
            v = o.get(k)
            if v is not None:
                s = self.m.string(v)
                if s is not None:
                    return {"text": redact(s)[:400]}
                return {"ref": self.m.t(v)[:80]}
        return {}

    def run(self) -> None:
        m = self.m
        calls = [n for n in _walk(m.root) if n.type in ("call_expression", "new_expression")]
        for n in calls:  # tools first, so agents can resolve tool variables
            self._tool(n)
        for n in calls:
            self._call(n)
        self._routes()

    def _callee(self, n: ts.Node) -> str | None:
        return self.m.qual(n.child_by_field_name("constructor") or n.child_by_field_name("function"))

    def _tool(self, n: ts.Node) -> None:
        m = self.m
        q = self._callee(n)
        if not q:
            return
        o = m.obj(m.first_obj_arg(n))
        if _pkg_is(q, "ai", "tool") or _pkg_is(q, "ai", "dynamicTool") or _pkg_is(q, "@mastra/core", "createTool") \
                or _pkg_is(q, "@openai/agents", "tool"):
            name = m.string(o.get("name")) or m.string(o.get("id")) or m.assigned_name(n) or "tool"
            body = m.t(o.get("execute")) if o.get("execute") is not None else ""
            fw = "vercel-ai" if q.startswith("ai#") else "mastra" if "mastra" in q else "openai-agents-js"
            var = m.assigned_name(n)
            fact = self._fact("tool", name, fw, n, description=m.string(o.get("description")) or "",
                              params=m.zod_keys(o.get("parameters") or o.get("inputSchema")), effects=text_effects(body, name))
            if var and not m.string(o.get("name")) and not m.string(o.get("id")):
                self.tool_vars[var] = name
                self.tool_facts[var] = fact
            elif var:
                self.tool_vars[var] = name
        elif _pkg_is(q, "@langchain/core", "tool"):
            cfg = m.obj(m.arg(n, 1)) if m.arg(n, 1) is not None and m.arg(n, 1).type == "object" else {}
            name = m.string(cfg.get("name")) or m.assigned_name(n) or "tool"
            if var := m.assigned_name(n):
                self.tool_vars[var] = name
            self._fact("tool", name, "langchain-js", n, description=m.string(cfg.get("description")) or "",
                       params=m.zod_keys(cfg.get("schema")), effects=text_effects(m.t(m.arg(n, 0)), name))
        elif q.endswith((".tool", ".registerTool")) and q.startswith("$"):
            var = q[1:].split(".")[0]
            if "McpServer" in (m.var_types.get(var) or "") or "Server" in (m.var_types.get(var) or ""):
                name = m.string(m.arg(n, 0)) or "tool"
                desc = m.string(m.arg(n, 1)) if m.arg(n, 1) is not None else ""
                if not desc and m.arg(n, 1) is not None and m.arg(n, 1).type == "object":
                    desc = m.string(m.obj(m.arg(n, 1)).get("description")) or ""
                last = m.arg(n, len((n.child_by_field_name("arguments") or n).named_children) - 1)
                self._fact("tool", name, "mcp", n, server_var=var, description=desc or "", mcp=True,
                           effects=text_effects(m.t(last), name))

    def _call(self, n: ts.Node) -> None:
        m = self.m
        q = self._callee(n)
        if not q:
            return
        o = m.obj(m.first_obj_arg(n))
        fn = m.enclosing_function(n)
        var = m.assigned_name(n)
        common = {"function": fn, "object": var, "exported": m.exported(var) or m.exported(fn), "tool_aliases": self.aliases_seen}
        if (_pkg_is(q, "ai", "generateText") or _pkg_is(q, "ai", "streamText") or _pkg_is(q, "ai", "generateObject")) and "tools" in o:
            self._fact("agent", fn or var or "agent", "vercel-ai", n, role="loop", tools=self._tool_names(o["tools"]),
                       model=self._model(o.get("model")), prompt=self._prompt(o), confidence="high", **{**common, "object": fn})
        elif _pkg_is(q, "ai", "Experimental_Agent") or _pkg_is(q, "ai", "ToolLoopAgent") or _pkg_is(q, "ai", "Agent"):
            self._fact("agent", var or fn or "agent", "vercel-ai", n, role="agent", tools=self._tool_names(o.get("tools")),
                       model=self._model(o.get("model")), prompt=self._prompt(o), confidence="high", **common)
        elif _pkg_is(q, "@mastra/core", "Agent"):
            self._fact("agent", m.string(o.get("name")) or var or "agent", "mastra", n, role="agent",
                       tools=self._tool_names(o.get("tools")), model=self._model(o.get("model")), prompt=self._prompt(o),
                       description=m.string(o.get("description")) or "", confidence="high", **common)
        elif _pkg_is(q, "@openai/agents", "Agent"):
            hand = o.get("handoffs")
            self._fact("agent", m.string(o.get("name")) or var or "agent", "openai-agents-js", n, role="agent",
                       tools=self._tool_names(o.get("tools")), model=self._model(o.get("model")), prompt=self._prompt(o),
                       members=[m.t(x) for x in hand.named_children] if hand is not None and hand.type == "array" else [],
                       description=m.string(o.get("handoffDescription")) or "", confidence="high", **common)
        elif _pkg_is(q, "@langchain/langgraph", "createReactAgent") or _pkg_is(q, "langchain", "createAgent"):
            self._fact("agent", var or fn or "agent", "langgraph-js", n, role="react", tools=self._tool_names(o.get("tools")),
                       model=self._model(o.get("llm") or o.get("model")), prompt=self._prompt(o), confidence="high", **common)
        elif _pkg_is(q, "@langchain/langgraph", "StateGraph"):
            self._fact("agent", var or fn or "graph", "langgraph-js", n, role="graph", tools=[], confidence="high", **common)
        elif _pkg_is(q, "@modelcontextprotocol/sdk", "McpServer") or _pkg_is(q, "@modelcontextprotocol/sdk", "Server"):
            self._fact("mcp_server", m.string(o.get("name")) or var or "server", "mcp", n, var=var,
                       command=None, language=m.sf.language)
        elif q.startswith("$") and q.endswith(("chat.completions.create", "responses.create", "messages.create")):
            var0 = q[1:].split(".")[0]
            vt = m.var_types.get(var0, "")
            if not (vt.startswith(("openai#", "@anthropic-ai/")) or m.llm_module):
                return
            if "tools" not in o:
                return
            prov = "anthropic" if "anthropic" in vt else "openai"
            self._fact("agent", fn or "agent", f"raw-{prov}", n, role="loop", tools=self._tool_names(o.get("tools")),
                       model=self._model(o.get("model")), prompt=self._prompt(o), confidence="medium", **{**common, "object": fn})
        elif q.startswith(("openai#", "@anthropic-ai/sdk#")) and n.type == "new_expression":
            base = o.get("baseURL")
            self._fact("llm_client", var or "client", q.split("#")[0], n, provider=q.split("#")[0],
                       hardcoded_base_url=m.string(base) if base is not None else None)
        elif "tools" in o and m.llm_module and not q.startswith("$this"):
            names = self._tool_names(o.get("tools"))
            if names:
                self._fact("agent", var or fn or q.split("#")[-1], "generic", n, role="fallback", tools=names,
                           model=self._model(o.get("model")), prompt=self._prompt(o), confidence="low", ctor=q, **common)
        # outside APIs: fetch("https://api.example.com/...")
        if self.m.t(n.child_by_field_name("function")) in ("fetch", "axios.post", "axios.get", "axios.delete", "axios.put"):
            url = m.string(m.arg(n, 0))
            mm = re.match(r"https?://([^/${]+)", url or "")
            if mm and mm.group(1) not in ("localhost", "127.0.0.1"):
                self._fact("external_api", mm.group(1), "http", n, base_url=f"https://{mm.group(1)}")

    def _routes(self) -> None:
        m = self.m
        apps = {v for v, t in m.var_types.items() if any(x in t for x in ("express#default", "hono#Hono", "fastify#default", "koa#default"))}
        for n in _walk(m.root):
            if n.type != "call_expression":
                continue
            q = self._callee(n) or ""
            if not q.startswith("$"):
                continue
            var, _, meth = q[1:].partition(".")
            if var in apps and meth in ("post", "get", "put", "all"):
                path = m.string(m.arg(n, 0)) or "/"
                self._fact("entrypoint", f"{meth.upper()} {path}", "http", n, kind="http", method=meth.upper(), route=path,
                           names_used=sorted(set(re.findall(r"[A-Za-z_]\w+", m.t(n)))))
        rel = m.sf.rel
        if re.search(r"(^|/)app/(.+/)?route\.(t|j)sx?$", rel) and re.search(r"export\s+(async\s+)?function\s+POST|export\s+const\s+POST", m.sf.text):
            route = "/" + re.sub(r"(^|.*/)app/|/?route\.(t|j)sx?$", "", rel)
            self._fact("entrypoint", f"POST {route}", "nextjs", m.root, kind="http", method="POST", route=route,
                       names_used=sorted(set(re.findall(r"[A-Za-z_]\w+", m.sf.text))))
        if re.search(r"(^|/)pages/api/.+\.(t|j)sx?$", rel):
            route = "/" + re.sub(r"(^|.*/)pages/|\.(t|j)sx?$", "", rel)
            self._fact("entrypoint", f"POST {route}", "nextjs", m.root, kind="http", method="POST", route=route,
                       names_used=sorted(set(re.findall(r"[A-Za-z_]\w+", m.sf.text))))


# ---------------------------------------------------------------- Go and Java


def _funcs(tree: ts.Tree, src: bytes, types: tuple[str, ...]) -> list[tuple[str, ts.Node]]:
    out = []
    for n in _walk(tree.root_node):
        if n.type in types:
            name = n.child_by_field_name("name")
            out.append((src[name.start_byte:name.end_byte].decode() if name else "?", n))
    return out


def _line_of(text: str, idx: int) -> int:
    return text.count("\n", 0, idx) + 1


def detect_go(sf: SourceFile, tree: ts.Tree, add: Callable[[Fact], str]) -> None:
    text, src = sf.text, sf.text.encode("utf-8")

    def fact(fact_kind: str, name: str, fw: str, idx: int, /, **attrs: Any) -> None:
        ln = _line_of(text, idx)
        add(Fact(kind=fact_kind, name=name, framework=fw, evidence=[Evidence(file=sf.rel, line=ln, snippet=sf.snippet(ln))],  # type: ignore[arg-type]
                 attrs={"file": sf.rel, "line": ln, "language": "go", **attrs}))

    for mm in re.finditer(r'server\.NewMCPServer\(\s*"([^"]+)"', text):
        fact("mcp_server", mm.group(1), "mcp-go", mm.start(), command=None, language="go")
    bodies = {re.sub(r"[^a-z0-9]", "", name.lower()): src[fn.start_byte:fn.end_byte].decode("utf-8", "replace")
              for name, fn in _funcs(tree, src, ("function_declaration", "method_declaration"))}

    def body_for(tool: str) -> str:
        key = re.sub(r"[^a-z0-9]", "", tool.lower())
        return bodies.get(key) or bodies.get(key + "handler") or bodies.get("handle" + key) or ""

    for mm in re.finditer(r'mcp\.NewTool\(\s*"([^"]+)"(?=(.{0,400}))', text, re.S):
        desc = re.search(r'WithDescription\(\s*"([^"]*)"', mm.group(2))
        fact("tool", mm.group(1), "mcp-go", mm.start(), mcp=True, description=desc.group(1) if desc else "",
             effects=text_effects(body_for(mm.group(1)), mm.group(1)))
    for mm in re.finditer(r'FunctionDefinition\{\s*Name\s*:\s*(?:openai\.F\()?"([^"]+)"\)?(?:,\s*Description\s*:\s*(?:openai\.F\()?"([^"]*)")?', text):
        fact("tool", mm.group(1), "raw-openai", mm.start(), description=mm.group(2) or "",
             effects=text_effects(body_for(mm.group(1)), mm.group(1)))
    for name, fn in _funcs(tree, src, ("function_declaration", "method_declaration")):
        body = src[fn.start_byte:fn.end_byte].decode("utf-8", "replace")
        start = fn.start_byte
        sdk = None
        if re.search(r"openai\.ChatCompletionRequest\{|openai\.ChatCompletionNewParams\{", body) and re.search(r"\bTools\s*:", body):
            sdk = "raw-openai"
        elif re.search(r"anthropic\.MessageNewParams\{", body) and re.search(r"\bTools\s*:", body):
            sdk = "raw-anthropic"
        elif re.search(r"agents\.(NewOneShotAgent|NewConversationalAgent|NewOpenAIFunctionsAgent)\(", body):
            sdk = "langchaingo"
        if sdk:
            tools = re.findall(r'Name\s*:\s*(?:openai\.F\()?"([a-z_][a-z0-9_]*)"', body)
            tools_var = re.search(r"\bTools\s*:\s*(\w+)", body)
            if tools_var:  # Tools: opsTools, defined at package level
                decl = re.search(rf"\b{tools_var.group(1)}\s*=\s*\[\][^{{]*\{{(.*?)\n\}}", text, re.S)
                if decl:
                    tools += re.findall(r'Name\s*:\s*(?:openai\.F\()?"([a-z_][a-z0-9_]*)"', decl.group(1))
            model = re.search(r'Model\s*:\s*(?:openai\.F\()?(?:openai\.)?"?([A-Za-z0-9_.\-]+)"?', body)
            fact("agent", name, sdk, start, role="loop", function=name, object=name, tools=sorted(set(tools)),
                 model={"value": model.group(1)} if model else {}, confidence="medium")
    for mm in re.finditer(r'(?:http\.HandleFunc|\.(?:POST|Post|HandleFunc|Handle))\(\s*"(/[^"]*)"', text):
        fact("entrypoint", f"POST {mm.group(1)}", "http", mm.start(), kind="http", method="POST", route=mm.group(1), names_used=[])


def detect_java(sf: SourceFile, tree: ts.Tree, add: Callable[[Fact], str]) -> None:
    text, src = sf.text, sf.text.encode("utf-8")

    def fact(fact_kind: str, name: str, fw: str, idx: int, /, **attrs: Any) -> None:
        ln = _line_of(text, idx)
        add(Fact(kind=fact_kind, name=name, framework=fw, evidence=[Evidence(file=sf.rel, line=ln, snippet=sf.snippet(ln))],  # type: ignore[arg-type]
                 attrs={"file": sf.rel, "line": ln, "language": "java", **attrs}))

    fw = "spring-ai" if "org.springframework.ai" in text else "langchain4j" if "dev.langchain4j" in text else None
    cls = re.search(r"class\s+(\w+)", text)
    for name, meth in _funcs(tree, src, ("method_declaration",)):
        head = src[meth.start_byte:meth.end_byte].decode("utf-8", "replace")
        mm = re.search(r'@Tool\s*(\(([^)]*)\))?', head)
        if mm and fw:
            args = mm.group(2) or ""
            tname = (re.search(r'name\s*=\s*"([^"]+)"', args) or [None, None])[1] or name
            desc = (re.search(r'(?:description\s*=\s*|^\s*)"([^"]*)"', args) or [None, ""])[1]
            body = head[head.find("{"):] if "{" in head else ""
            fact("tool", tname, fw, meth.start_byte, description=desc, holder=cls.group(1) if cls else None,
                 effects=text_effects(body, name))
    if fw:
        for mm in re.finditer(r"AiServices\.(?:builder|create)\(\s*(\w+)\.class", text):
            tools = re.findall(r"\.tools\(\s*([^)]*)\)", text)
            fact("agent", mm.group(1), "langchain4j", mm.start(), role="agent", object=mm.group(1), tools=[],
                 tool_holders=[t.strip() for t in tools], confidence="high")
        for mm in re.finditer(r"ChatClient\.(?:builder|create)\(|ChatClient\.Builder\s+\w+", text):
            var = re.search(r"\bChatClient\s+(\w+)\s*[;=]", text) or re.search(r"(\w+)\s*=\s*[\w.]*ChatClient\.(?:builder|create)", text)
            sys_prompt = re.search(r'defaultSystem\(\s*"([^"]*)"', text)
            holders = [h.strip() for grp in re.findall(r"\.(?:defaultTools|tools)\(\s*([^)]*)\)", text) for h in grp.split(",") if h.strip()]
            types = {v: t for t, v in re.findall(r"\b([A-Z]\w+)\s+(\w+)\s*[,;)=]", text)}
            fact("agent", var.group(1) if var else (cls.group(1) if cls else "chat_client"), "spring-ai", mm.start(), role="agent",
                 object=cls.group(1) if cls else None, tools=[], tool_holders=[types.get(h, h) for h in holders],
                 prompt={"text": sys_prompt.group(1)[:400]} if sys_prompt else {}, confidence="medium")
    for mm in re.finditer(r'@(Post|Get)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?"(/[^"]*)"', text):
        fact("entrypoint", f"{mm.group(1).upper()} {mm.group(2)}", "http", mm.start(), kind="http",
             method=mm.group(1).upper(), route=mm.group(2), names_used=[])


def detect_code(inv: Inventory, add: Callable[[Fact], str]) -> int:
    n = 0
    for sf in inv.code("typescript", "javascript", "go", "java"):
        tree = _parse(sf)
        if tree is None:
            continue
        n += 1
        if sf.language in ("typescript", "javascript"):
            TsDetector(TsModule(sf, tree), add).run()
        elif sf.language == "go":
            detect_go(sf, tree, add)
        elif sf.language == "java":
            detect_java(sf, tree, add)
    return n
