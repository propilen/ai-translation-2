package local.linguaflow.nlp;

import java.nio.file.Path;
import java.time.Duration;

public final class Demo {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) {
            System.err.println("Usage: Demo <worker.exe> <glossary.tsv>");
            System.exit(2);
        }
        try (var worker = new NlpWorkerClient(Path.of(args[0]), System.err::println)) {
            var timeout = Duration.ofSeconds(60); // First model load can take a few seconds.
            System.out.println(worker.request("ping", null, timeout).get());
            var load = worker.fields().put("glossary_id", "demo").put("lang", "de").put("path", args[1]);
            System.out.println(worker.request("load_glossary", load, timeout).get());
            var search = worker.fields().put("glossary_id", "demo").put("lang", "de")
                    .put("text", "Die Fahrzeuge werden überprüft");
            System.out.println(worker.request("find_terms", search, timeout).get());
        }
    }
}
