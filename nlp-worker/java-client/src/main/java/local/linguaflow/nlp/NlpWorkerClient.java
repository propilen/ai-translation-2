package local.linguaflow.nlp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;
import javax.swing.SwingUtilities;

/** Persistent JSON Lines client. request() is asynchronous and safe to call from Swing code. */
public final class NlpWorkerClient implements AutoCloseable {
    private final ObjectMapper mapper = new ObjectMapper();
    private final Process process;
    private final BufferedWriter input;
    private final Map<Long, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();
    private final AtomicLong nextId = new AtomicLong();
    private final ExecutorService writer = Executors.newSingleThreadExecutor(
            Thread.ofPlatform().daemon().name("nlp-worker-writer").factory());
    private final Thread stdoutReader;
    private final Thread stderrReader;
    private volatile boolean closed;

    public NlpWorkerClient(Path executable, Consumer<String> diagnostics) throws IOException {
        this(List.of(executable.toAbsolutePath().toString()), diagnostics);
    }

    /** The command-list overload also permits integration testing with Python source. */
    public NlpWorkerClient(List<String> command, Consumer<String> diagnostics) throws IOException {
        if (SwingUtilities.isEventDispatchThread()) throw new IllegalStateException("Start worker off the Swing EDT");
        Objects.requireNonNull(command);
        Objects.requireNonNull(diagnostics);
        process = new ProcessBuilder(command).start();
        input = new BufferedWriter(new OutputStreamWriter(process.getOutputStream(), StandardCharsets.UTF_8));
        stdoutReader = Thread.ofPlatform().daemon().name("nlp-worker-stdout").start(this::readStdout);
        stderrReader = Thread.ofPlatform().daemon().name("nlp-worker-stderr").start(() -> readStderr(diagnostics));
        process.onExit().thenAccept(p -> failPending(new IOException("NLP worker exited with code " + p.exitValue())));
    }

    public CompletableFuture<JsonNode> request(String action, ObjectNode fields, Duration timeout) {
        Objects.requireNonNull(action);
        Objects.requireNonNull(timeout);
        if (timeout.isZero() || timeout.isNegative()) throw new IllegalArgumentException("timeout must be positive");
        long id = nextId.incrementAndGet();
        CompletableFuture<JsonNode> future = new CompletableFuture<>();
        ObjectNode message = fields == null ? mapper.createObjectNode() : fields.deepCopy();
        message.put("id", id);
        message.put("action", action);
        if (closed || !process.isAlive()) {
            future.completeExceptionally(new IOException("NLP worker is not running"));
            return future;
        }
        pending.put(id, future);
        future.orTimeout(timeout.toMillis(), TimeUnit.MILLISECONDS).whenComplete((ignored, error) -> pending.remove(id, future));
        try {
            writer.execute(() -> {
                try {
                    input.write(mapper.writeValueAsString(message));
                    input.newLine();
                    input.flush();
                } catch (IOException error) {
                    pending.remove(id);
                    future.completeExceptionally(error);
                }
            });
        } catch (RejectedExecutionException error) {
            pending.remove(id);
            future.completeExceptionally(error);
        }
        return future;
    }

    public ObjectNode fields() { return mapper.createObjectNode(); }

    private void readStdout() {
        try (var reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                JsonNode response = mapper.readTree(line);
                JsonNode id = response.get("id");
                if (id == null || !id.canConvertToLong()) continue;
                CompletableFuture<JsonNode> future = pending.remove(id.longValue());
                if (future == null) continue;
                if (response.path("ok").asBoolean(false)) future.complete(response);
                else future.completeExceptionally(new WorkerException(response.path("error").path("code").asText("UNKNOWN"),
                        response.path("error").path("message").asText("Worker error")));
            }
        } catch (Exception error) {
            failPending(error);
        } finally {
            failPending(new IOException("NLP worker stdout closed"));
        }
    }

    private void readStderr(Consumer<String> diagnostics) {
        try (var reader = new BufferedReader(new InputStreamReader(process.getErrorStream(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                try { diagnostics.accept(line); }
                catch (RuntimeException ignored) { /* Keep draining stderr even if a logger fails. */ }
            }
        } catch (IOException ignored) { /* Process exit closes this stream. */ }
    }

    private void failPending(Exception error) {
        pending.forEach((id, future) -> future.completeExceptionally(error));
        pending.clear();
    }

    @Override public void close() {
        if (SwingUtilities.isEventDispatchThread()) throw new IllegalStateException("Close worker off the Swing EDT");
        if (closed) return;
        boolean acknowledged = false;
        try {
            if (process.isAlive()) {
                request("shutdown", null, Duration.ofSeconds(3)).get(3, TimeUnit.SECONDS);
                acknowledged = true;
            }
        } catch (Exception ignored) {
            // A dead or unresponsive worker must still be reaped.
        } finally {
            closed = true;
            writer.shutdownNow();
            if (!acknowledged && process.isAlive()) process.destroyForcibly();
            try { input.close(); } catch (IOException ignored) { }
            if (process.isAlive()) {
                try {
                    if (!process.waitFor(2, TimeUnit.SECONDS)) process.destroyForcibly();
                } catch (InterruptedException error) {
                    Thread.currentThread().interrupt();
                    process.destroyForcibly();
                }
            }
            failPending(new IOException("NLP worker client closed"));
        }
    }

    public static final class WorkerException extends IOException {
        private final String code;
        public WorkerException(String code, String message) { super(message); this.code = code; }
        public String code() { return code; }
    }
}
