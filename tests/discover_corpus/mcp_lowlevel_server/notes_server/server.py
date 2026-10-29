import httpx
import mcp.types as types
from mcp.server.lowlevel import Server

from . import storage

server = Server("team-notes")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_notes",
            description="List note topics and how many notes each has.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="read_note",
            description="Read all notes under a topic.",
            inputSchema={
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        ),
        types.Tool(
            name="append_note",
            description="Append a note to a topic.",
            inputSchema={
                "type": "object",
                "properties": {"topic": {"type": "string"}, "body": {"type": "string"}},
                "required": ["topic", "body"],
            },
        ),
        types.Tool(
            name="purge_notes",
            description="Delete every note under a topic. Irreversible.",
            inputSchema={
                "type": "object",
                "properties": {"topic": {"type": "string"}},
                "required": ["topic"],
            },
        ),
        types.Tool(
            name="import_from_url",
            description="Fetch a web page and store its text as a note.",
            inputSchema={
                "type": "object",
                "properties": {"topic": {"type": "string"}, "url": {"type": "string"}},
                "required": ["topic", "url"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "list_notes":
        text = "\n".join(f"{t}: {n}" for t, n in storage.list_topics()) or "(no notes)"
    elif name == "read_note":
        text = "\n---\n".join(storage.read_topic(arguments["topic"]))
    elif name == "append_note":
        note_id = storage.append(arguments["topic"], arguments["body"])
        text = f"saved note {note_id}"
    elif name == "purge_notes":
        text = f"deleted {storage.purge(arguments['topic'])} notes"
    elif name == "import_from_url":
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as client:
            resp = await client.get(arguments["url"])
        note_id = storage.append(arguments["topic"], resp.text[:10000])
        text = f"imported {len(resp.text)} chars as note {note_id}"
    else:
        raise ValueError(f"Unknown tool: {name}")
    return [types.TextContent(type="text", text=text)]
