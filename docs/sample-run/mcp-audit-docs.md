## MCP Audit · docs

**Grade D (64/100)** · protocol `2025-11-25` · 3 tools · 2.3s

| Suite | Score | Findings |
|---|---|---|
| conformance | 100 (A) | 0 |
| tool quality | 59 (F) | 4 |
| robustness | 90 (A) | 1 |
| security | 60 (D) | 1 |
| performance | 100 (A) | 0 |

### Findings

- 🟥 **critical** · security · `read_document` · Path traversal: reads arbitrary files outside its root  
  <sub>param 'path' returned a canary file planted outside the server's directory (payload 'C:\\Users\\sahus\\AppData\\Local\\Temp\\crucible-canary-_md_56l5\\canary.txt')</sub>
- 🟧 **high** · tool_quality · `find` · Tool has no description; models must guess what it does
- 🟨 **medium** · tool_quality · `find` · Cryptic parameter names  
  <sub>q</sub>
- 🟨 **medium** · robustness · `read_document` · Unhandled exception on bad input (internal error leaked)  
  <sub>path: empty string → Error executing tool read_document: [Errno 13] Permission denied: 'E:\\projects\\resume-projects\\agentcrucible\\examples\\support-agent\\kb'</sub>
- ⬜ **low** · tool_quality · `read_document` · Parameters without descriptions  
  <sub>path</sub>
- ⬜ **low** · tool_quality · `find` · Parameters without descriptions  
  <sub>q</sub>
Latency of `list_documents`: p50 24.5 ms · p95 40.5 ms at concurrency 5.

Badge: `![MCP audit](https://img.shields.io/badge/MCP%20audit-D%2064-orange)`
