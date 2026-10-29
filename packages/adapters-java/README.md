# AgentCrucible adapters for Java

One file, no dependencies, Java 17+: [`AgentCrucible.java`](src/main/java/dev/agentcrucible/AgentCrucible.java).

`crucible discover` copies it next to the adapter it generates and starts your agent with it:

```bash
mvn -q -DskipTests package dependency:copy-dependencies     # build first
java agent-tests/adapters/support/AgentCrucible.java --classpath target/classes,target/dependency \
     com.acme.SupportService chat --spring com.acme.SupportApplication
```

It calls `chat(String message)` once per user message: a static method, a method on a class with a no-argument
constructor, or (with `--spring`) a bean of your Spring Boot application, started without its web server.

As a library: `AgentCrucible.serve(history -> agent.answer(AgentCrucible.last(history)))`, and wrap tools with
`AgentCrucible.traceTool("get_order", args -> ...)` so their calls are traced and scenarios can mock or block them
(including document-snapshot mocks for RAG tests).
