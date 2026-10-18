package local.linguaflow.nlp;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;
import com.fasterxml.jackson.databind.JsonNode;
import javax.swing.SwingUtilities;

/** Run with <python.exe> <worker.py>, or one argument <nlp-worker.exe>. */
public final class ClientSmoke {
    public static void main(String[] args) throws Exception {
        if (args.length != 1 && args.length != 2) throw new IllegalArgumentException("Supply EXE or Python plus worker.py");
        Path glossary = Files.createTempFile("nlp-worker-smoke-", ".tsv");
        try {
            Files.writeString(glossary, "Fahrzeug\tавтомобиль\n", java.nio.charset.StandardCharsets.UTF_8);
            try (var worker = new NlpWorkerClient(List.of(args), System.err::println)) {
                var timeout = Duration.ofSeconds(60);
                if (!worker.request("ping", null, timeout).get().path("status").asText().equals("ready"))
                    throw new AssertionError("ping failed");
                var load = worker.fields().put("glossary_id", "audi").put("lang", "de").put("path", glossary.toString());
                if (worker.request("load_glossary", load, timeout).get().path("count").asInt() != 1)
                    throw new AssertionError("load failed");
                AtomicReference<CompletableFuture<JsonNode>> fromEdt = new AtomicReference<>();
                SwingUtilities.invokeAndWait(() -> fromEdt.set(worker.request("ping", null, timeout)));
                if (!fromEdt.get().get().path("status").asText().equals("ready"))
                    throw new AssertionError("asynchronous EDT request failed");
                for (int i = 0; i < 100; i++) {
                    var query = worker.fields().put("glossary_id", "audi").put("lang", "de").put("text", "Die Fahrzeuge");
                    var terms = worker.request("find_terms", query, timeout).get().path("terms");
                    if (terms.size() != 1 || !terms.get(0).path("target").asText().equals("автомобиль"))
                        throw new AssertionError("search failed: " + terms);
                }
                try {
                    worker.request("unknown", null, timeout).get();
                    throw new AssertionError("expected protocol error");
                } catch (ExecutionException expected) {
                    if (!(expected.getCause() instanceof NlpWorkerClient.WorkerException error)
                            || !error.code().equals("UNKNOWN_ACTION")) throw expected;
                }
            }
            try (var exited = new NlpWorkerClient(List.of("cmd.exe", "/c", "exit", "7"), System.err::println)) {
                try {
                    exited.request("ping", null, Duration.ofSeconds(5)).get();
                    throw new AssertionError("expected failure after unexpected process exit");
                } catch (ExecutionException expected) {
                    // The client must fail pending requests when the process disappears.
                }
            }
            System.out.println("Java client smoke passed");
        } finally {
            Files.deleteIfExists(glossary);
        }
    }
}
