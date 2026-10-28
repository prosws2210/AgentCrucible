## MCP Audit · shop

**Grade D (64/100)** · protocol `2025-11-25` · 6 tools · 2.9s

| Suite | Score | Findings |
|---|---|---|
| conformance | 100 (A) | 0 |
| tool quality | 76 (C) | 8 |
| robustness | 90 (A) | 1 |
| security | 60 (D) | 1 |
| performance | 100 (A) | 0 |

### Findings

- 🟥 **critical** · security · `get_order` · SQL injection: tautology returns data a normal lookup doesn't  
  <sub>param 'order_id' with "' OR '1'='1" → {
  "id": "A-1042",
  "customer_id": 1,
  "item": "Wireless Mouse",
  "total": 49.99,
  "status": "delivered",
  "placed_on": "2026-10-02"
}</sub>
- 🟨 **medium** · robustness · `get_order` · Unhandled exception on bad input (internal error leaked)  
  <sub>order_id: empty string → Error executing tool get_order: list index out of range</sub>
- ⬜ **low** · tool_quality · `find_customer` · Parameters without descriptions  
  <sub>email</sub>
- ⬜ **low** · tool_quality · `list_orders` · Parameters without descriptions  
  <sub>customer_id</sub>
- ⬜ **low** · tool_quality · `get_order` · Parameters without descriptions  
  <sub>order_id</sub>
- ⬜ **low** · tool_quality · `issue_refund` · Parameters without descriptions  
  <sub>order_id, reason</sub>
- ⬜ **low** · tool_quality · `issue_refund` · Likely destructive tool without destructiveHint annotation
- ⬜ **low** · tool_quality · `cancel_order` · Parameters without descriptions  
  <sub>order_id</sub>
- ⬜ **low** · tool_quality · `cancel_order` · Likely destructive tool without destructiveHint annotation
- ⬜ **low** · tool_quality · `search_products` · Parameters without descriptions  
  <sub>query</sub>
Latency of `find_customer`: p50 22.1 ms · p95 31.4 ms at concurrency 5.

Badge: `![MCP audit](https://img.shields.io/badge/MCP%20audit-D%2064-orange)`
