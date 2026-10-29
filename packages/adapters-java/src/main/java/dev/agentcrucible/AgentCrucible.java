package dev.agentcrucible;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.io.PrintStream;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.net.URI;
import java.net.URL;
import java.net.URLClassLoader;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Function;

/**
 * Lets AgentCrucible drive a Java agent: the stdio protocol (one JSON line per turn), tool tracing, and the scenario's
 * mocks, blocked tools and injected text, like the Python, TypeScript and Go adapters. One file, no dependencies,
 * Java 17+.
 *
 * <p>As a launcher (what `crucible discover` generates), it loads your compiled classes and calls one method per turn:
 * <pre>
 *   java AgentCrucible.java --classpath target/classes,target/dependency com.acme.SupportAgent answer
 *   java AgentCrucible.java --classpath ... com.acme.SupportService chat --spring com.acme.SupportApplication
 * </pre>
 * The method takes the user's message (String) and returns the reply; it may be static, on a class with a no-argument
 * constructor, or (with --spring) on a bean of your Spring Boot application, started without its web server.
 *
 * <p>As a library: {@code AgentCrucible.serve(history -> myAgent.answer(last(history)))}, and wrap tools with
 * {@link #traceTool(String, Function)}.
 */
public final class AgentCrucible {
    private AgentCrucible() {}

    public record Message(String role, String content) {}

    // ------------------------------------------------------------ protocol

    /** Run the stdio protocol until stdin closes or an {"type":"end"} line arrives. */
    public static void serve(Function<List<Message>, String> turn) throws Exception {
        PrintStream out = new PrintStream(new java.io.FileOutputStream(java.io.FileDescriptor.out), true, StandardCharsets.UTF_8);
        System.setOut(System.err); // stray System.out.println calls must not corrupt the protocol
        BufferedReader in = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
        List<Message> history = new ArrayList<>();
        for (String line; (line = in.readLine()) != null; ) {
            Object parsed;
            try {
                parsed = Json.parse(line);
            } catch (RuntimeException e) {
                continue;
            }
            if (!(parsed instanceof Map<?, ?> msg)) continue;
            Object type = msg.get("type");
            if ("end".equals(type)) break;
            if (!"user".equals(type)) continue;
            history.add(new Message("user", String.valueOf(msg.get("content"))));
            String reply;
            try {
                reply = turn.apply(List.copyOf(history));
            } catch (Throwable e) {
                Throwable c = e.getCause() != null && e instanceof java.lang.reflect.InvocationTargetException ? e.getCause() : e;
                c.printStackTrace();
                reply = "[agent error] " + c.getClass().getSimpleName() + ": " + c.getMessage();
            }
            history.add(new Message("assistant", reply == null ? "" : reply));
            Map<String, Object> answer = new LinkedHashMap<>();
            answer.put("type", "assistant");
            answer.put("content", reply == null ? "" : reply);
            out.println(Json.write(answer));
        }
    }

    public static String last(List<Message> history) {
        return history.get(history.size() - 1).content();
    }

    // ------------------------------------------------------------ launcher

    public static void main(String[] args) throws Exception {
        System.setOut(System.err); // logs (Spring's banner included) go to stderr; serve() answers on the real stdout
        List<String> rest = new ArrayList<>();
        String classpath = "", spring = null;
        for (int i = 0; i < args.length; i++) {
            if (args[i].equals("--classpath") && i + 1 < args.length) classpath = args[++i];
            else if (args[i].equals("--spring") && i + 1 < args.length) spring = args[++i];
            else rest.add(args[i]);
        }
        if (rest.size() != 2) {
            System.err.println("usage: java AgentCrucible.java [--classpath dirs,jars] [--spring app.Class] com.acme.Agent method");
            System.exit(2);
        }
        ClassLoader loader = new URLClassLoader(urls(classpath), AgentCrucible.class.getClassLoader());
        Thread.currentThread().setContextClassLoader(loader);
        Class<?> cls = Class.forName(rest.get(0), true, loader);
        Method method = null;
        for (Method m : cls.getMethods()) {
            if (m.getName().equals(rest.get(1)) && m.getParameterCount() == 1 && m.getParameterTypes()[0] == String.class) method = m;
        }
        if (method == null) throw new NoSuchMethodException(rest.get(0) + "." + rest.get(1) + "(String)");
        Object target = Modifier.isStatic(method.getModifiers()) ? null
            : spring != null ? springBean(Class.forName(spring, true, loader), cls) : cls.getDeclaredConstructor().newInstance();
        Method m = method;
        serve(history -> {
            try {
                Object r = m.invoke(target, last(history));
                return r == null ? "" : r.toString();
            } catch (ReflectiveOperationException e) {
                throw new RuntimeException(e.getCause() != null ? e.getCause() : e);
            }
        });
    }

    static URL[] urls(String classpath) throws Exception {
        List<URL> out = new ArrayList<>();
        for (String entry : classpath.split(",")) {
            entry = entry.trim().replaceAll("[/\\\\]\\*$", "");
            if (entry.isEmpty()) continue;
            File f = new File(entry);
            if (f.isDirectory()) {
                out.add(f.toURI().toURL()); // a classes folder
                File[] jars = f.listFiles((d, n) -> n.endsWith(".jar"));
                if (jars != null) for (File j : jars) out.add(j.toURI().toURL()); // or a folder of dependency jars
            } else if (f.isFile()) out.add(f.toURI().toURL());
        }
        return out.toArray(new URL[0]);
    }

    /** Start the Spring Boot application without its web server and return the bean of `type`. */
    static Object springBean(Class<?> app, Class<?> type) throws Exception {
        ClassLoader l = app.getClassLoader();
        Class<?> builderCls = Class.forName("org.springframework.boot.builder.SpringApplicationBuilder", true, l);
        Class<?> webType = Class.forName("org.springframework.boot.WebApplicationType", true, l);
        Object builder = builderCls.getConstructor(Class[].class).newInstance((Object) new Class<?>[] {app});
        builder = builderCls.getMethod("web", webType).invoke(builder, webType.getField("NONE").get(null));
        Object ctx = builderCls.getMethod("run", String[].class).invoke(builder, (Object) new String[0]);
        return ctx.getClass().getMethod("getBean", Class.class).invoke(ctx, type);
    }

    // ------------------------------------------------------------ tools

    /** Report tool events to the episode's gateway (a no-op outside a test run). */
    @SafeVarargs
    public static void emit(Map<String, Object>... events) {
        String url = System.getenv("CRUCIBLE_EVENTS_URL");
        if (url == null || url.isEmpty()) return;
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(5))
                .header("Content-Type", "application/json").POST(HttpRequest.BodyPublishers.ofString(Json.write(java.util.Arrays.stream(events).toList()))).build();
            HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.discarding());
        } catch (Exception e) {
            System.err.println("[agentcrucible] tracing failed: " + e);
        }
    }

    @SuppressWarnings("unchecked")
    static <T> T env(String name, T fallback) {
        String v = System.getenv(name);
        if (v == null || v.isEmpty()) return fallback;
        try {
            return (T) Json.parse(v);
        } catch (RuntimeException e) {
            return fallback;
        }
    }

    static Map<String, Object> event(Object... kv) {
        Map<String, Object> m = new LinkedHashMap<>();
        for (int i = 0; i + 1 < kv.length; i += 2) m.put((String) kv[i], kv[i + 1]);
        return m;
    }

    static String clip(String s) {
        return s.length() > 4000 ? s.substring(0, 4000) : s;
    }

    /** Wrap a tool (JSON-like arguments in, text out): traced, and the scenario's mock / block / inject applies. */
    @SuppressWarnings("unchecked")
    public static Function<Map<String, Object>, String> traceTool(String name, Function<Map<String, Object>, String> fn) {
        return args -> {
            Map<String, Object> call = event("type", "tool_call", "tool", name, "args", args);
            if (env("CRUCIBLE_DENY_TOOLS", List.<Object>of()).contains(name)) {
                String text = "Tool '" + name + "' is blocked by test policy.";
                call.put("blocked", true);
                emit(call, event("type", "tool_result", "tool", name, "content", text, "is_error", true));
                return text;
            }
            Map<String, Object> mocks = env("CRUCIBLE_TOOL_MOCKS", Map.<String, Object>of());
            if (mocks.containsKey(name)) {
                Object mock = mocks.get(name);
                String text = mock instanceof Map<?, ?> m && m.get("snapshot") instanceof String path
                    ? snapshotAnswer(path, queryOf(args), m.get("k") instanceof Number k ? k.intValue() : 3)
                    : mock instanceof String s ? s : Json.write(mock);
                call.put("mocked", true);
                emit(call, event("type", "tool_result", "tool", name, "content", clip(text)));
                return text;
            }
            emit(call);
            long start = System.currentTimeMillis();
            try {
                String result = fn.apply(args);
                Map<String, Object> injects = env("CRUCIBLE_TOOL_INJECT", Map.<String, Object>of());
                Object inject = injects.get(name);
                if (inject instanceof String s && !s.isEmpty()) result = result + "\n\n" + s;
                emit(event("type", "tool_result", "tool", name, "content", clip(result), "duration_ms", System.currentTimeMillis() - start));
                return result;
            } catch (RuntimeException e) {
                emit(event("type", "tool_result", "tool", name, "content", e.toString(), "is_error", true));
                throw e;
            }
        };
    }

    // ------------------------------------------------------------ RAG snapshots (same index as agentcrucible.snapshot)

    static final Set<String> STOP = new HashSet<>(List.of(("a an and are as at be but by can do does for from has have how i if in into is it its me my no not of on " +
        "or our please so than that the their them then there these they this to was we what when where which who why will " +
        "with you your about any some tell know find check give get").split(" ")));
    static final java.util.regex.Pattern WORD = java.util.regex.Pattern.compile("[a-z0-9][a-z0-9\\-]{1,}");

    static List<String> words(String t) {
        List<String> out = new ArrayList<>();
        java.util.regex.Matcher m = WORD.matcher(t.toLowerCase());
        while (m.find()) if (!STOP.contains(m.group())) out.add(m.group());
        return out;
    }

    static String queryOf(Map<String, Object> args) {
        for (String k : List.of("query", "question", "q", "input", "text", "search", "search_query", "prompt", "message", "topic")) {
            if (args != null && args.get(k) instanceof String s) return s;
        }
        String best = "";
        if (args != null) for (Object v : args.values()) if (v instanceof String s && s.length() > best.length()) best = s;
        return best;
    }

    @SuppressWarnings("unchecked")
    public static List<Map<String, Object>> searchSnapshot(String path, String query, int k) {
        Map<String, Object> snap;
        try {
            snap = (Map<String, Object>) Json.parse(Files.readString(Path.of(path)));
        } catch (Exception e) {
            return List.of();
        }
        List<Map<String, Object>> passages = (List<Map<String, Object>>) snap.getOrDefault("passages", List.of());
        int n = Math.max(passages.size(), 1);
        List<Map<String, Integer>> tfs = new ArrayList<>();
        Map<String, Integer> df = new HashMap<>();
        int total = 0;
        for (Map<String, Object> p : passages) {
            Map<String, Integer> tf = new HashMap<>();
            for (String w : words(p.get("source") + " " + p.get("text"))) {
                tf.merge(w, 1, Integer::sum);
                total++;
            }
            tf.keySet().forEach(w -> df.merge(w, 1, Integer::sum));
            tfs.add(tf);
        }
        double avg = total > 0 ? (double) total / n : 1.0;
        Set<String> q = new HashSet<>(words(query));
        List<double[]> scored = new ArrayList<>();
        for (int i = 0; i < tfs.size(); i++) {
            Map<String, Integer> tf = tfs.get(i);
            int len = tf.values().stream().mapToInt(Integer::intValue).sum();
            double s = 0;
            for (String w : q) {
                Integer f = tf.get(w);
                if (f == null) continue;
                int c = df.get(w);
                s += Math.log(1 + (n - c + 0.5) / (c + 0.5)) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len / avg));
            }
            if (s > 0) scored.add(new double[] {s, i});
        }
        scored.sort((a, b) -> Double.compare(b[0], a[0]));
        List<Map<String, Object>> out = new ArrayList<>();
        for (int j = 0; j < Math.min(k, scored.size()); j++) out.add(passages.get((int) scored.get(j)[1]));
        return out;
    }

    static String snapshotAnswer(String path, String query, int k) {
        List<Map<String, Object>> hits = searchSnapshot(path, query, k);
        if (hits.isEmpty()) return "No results.";
        StringBuilder sb = new StringBuilder();
        for (Map<String, Object> h : hits) {
            if (sb.length() > 0) sb.append("\n\n");
            sb.append('[').append(h.get("source")).append("]\n").append(h.get("text"));
        }
        return sb.toString();
    }

    // ------------------------------------------------------------ JSON (just enough for the protocol and settings)

    static final class Json {
        private final String s;
        private int i;

        private Json(String s) {
            this.s = s;
        }

        static Object parse(String text) {
            Json p = new Json(text);
            Object v = p.value();
            p.ws();
            if (p.i != p.s.length()) throw new IllegalArgumentException("trailing characters");
            return v;
        }

        private void ws() {
            while (i < s.length() && Character.isWhitespace(s.charAt(i))) i++;
        }

        private Object value() {
            ws();
            if (i >= s.length()) throw new IllegalArgumentException("unexpected end");
            char c = s.charAt(i);
            if (c == '{') {
                Map<String, Object> m = new LinkedHashMap<>();
                i++;
                ws();
                if (s.charAt(i) == '}') {
                    i++;
                    return m;
                }
                while (true) {
                    ws();
                    String key = string();
                    ws();
                    i++; // ':'
                    m.put(key, value());
                    ws();
                    if (s.charAt(i++) == '}') return m;
                }
            }
            if (c == '[') {
                List<Object> l = new ArrayList<>();
                i++;
                ws();
                if (s.charAt(i) == ']') {
                    i++;
                    return l;
                }
                while (true) {
                    l.add(value());
                    ws();
                    if (s.charAt(i++) == ']') return l;
                }
            }
            if (c == '"') return string();
            if (s.startsWith("true", i)) {
                i += 4;
                return true;
            }
            if (s.startsWith("false", i)) {
                i += 5;
                return false;
            }
            if (s.startsWith("null", i)) {
                i += 4;
                return null;
            }
            int start = i;
            while (i < s.length() && "+-0123456789.eE".indexOf(s.charAt(i)) >= 0) i++;
            if (start == i) throw new IllegalArgumentException("unexpected character " + c);
            return Double.parseDouble(s.substring(start, i));
        }

        private String string() {
            if (s.charAt(i) != '"') throw new IllegalArgumentException("expected a string");
            StringBuilder sb = new StringBuilder();
            i++;
            while (true) {
                char c = s.charAt(i++);
                if (c == '"') return sb.toString();
                if (c != '\\') {
                    sb.append(c);
                    continue;
                }
                char e = s.charAt(i++);
                switch (e) {
                    case 'n' -> sb.append('\n');
                    case 't' -> sb.append('\t');
                    case 'r' -> sb.append('\r');
                    case 'b' -> sb.append('\b');
                    case 'f' -> sb.append('\f');
                    case 'u' -> {
                        sb.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        i += 4;
                    }
                    default -> sb.append(e);
                }
            }
        }

        static String write(Object v) {
            StringBuilder sb = new StringBuilder();
            write(v, sb);
            return sb.toString();
        }

        private static void write(Object v, StringBuilder sb) {
            if (v == null) sb.append("null");
            else if (v instanceof String str) {
                sb.append('"');
                for (char c : str.toCharArray()) {
                    switch (c) {
                        case '"' -> sb.append("\\\"");
                        case '\\' -> sb.append("\\\\");
                        case '\n' -> sb.append("\\n");
                        case '\r' -> sb.append("\\r");
                        case '\t' -> sb.append("\\t");
                        default -> {
                            if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                            else sb.append(c);
                        }
                    }
                }
                sb.append('"');
            } else if (v instanceof Map<?, ?> m) {
                sb.append('{');
                boolean first = true;
                for (Map.Entry<?, ?> e : m.entrySet()) {
                    if (!first) sb.append(',');
                    first = false;
                    write(String.valueOf(e.getKey()), sb);
                    sb.append(':');
                    write(e.getValue(), sb);
                }
                sb.append('}');
            } else if (v instanceof Iterable<?> it) {
                sb.append('[');
                boolean first = true;
                for (Object o : it) {
                    if (!first) sb.append(',');
                    first = false;
                    write(o, sb);
                }
                sb.append(']');
            } else if (v instanceof Number || v instanceof Boolean) sb.append(v);
            else write(v.toString(), sb);
        }
    }
}
