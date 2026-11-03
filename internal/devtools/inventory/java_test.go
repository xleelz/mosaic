package main

import (
	"sort"
	"strings"
	"testing"
)

func TestScanJava(t *testing.T) {
	got, err := Scan("../testdata/inventory/java", Options{})
	if err != nil {
		t.Fatal(err)
	}
	have := map[string]Entry{}
	var keys []string
	for _, e := range got {
		k := e.Kind + " " + e.Name
		have[k] = e
		keys = append(keys, k+" @"+e.File)
	}
	sort.Strings(keys)
	want := []string{
		"messaging-verb MUTATION_RSP",
		"messaging-verb MUTATION_REQ",
		"messaging-verb COUNTER_REQ",
		"messaging-verb OLD_RSP",
		"verb-handler ResponseVerbHandler.doVerb",
		"verb-handler AbstractMutationVerbHandler.doVerb",
		"verb-handler MutationVerbHandler.doVerb",
		"verb-handler CounterVerbHandler",
		"verb-handler CleanupRequest.createVerbHandler",
		"verb-handler CleanupRequest.inline",
		"verb-handler CleanupRequest.anonymous$1.doVerb",
		"native-message QUERY",
		"native-message STARTUP",
		"cql-statement SelectStatement",
		"cql-statement AlterSchemaStatement",
		"cql-statement CreateTableStatement",
		"cql-statement AlterTableStatement.AddColumns",
		"cli-command nodetool status",
		"cli-command nodetool repair_admin list",
		"cli-command nodetool orphan",
		"jmx-operation StorageServiceMBean.getLiveNodes",
		"jmx-operation StorageServiceMBean.setCompactionThroughput",
		"jmx-operation StorageServiceMBean.isJoined",
		"jmx-operation StorageServiceMBean.forceKeyspaceCompaction",
		"jmx-operation StorageServiceMBean.getTokenToEndpointMap",
		"jmx-operation StorageServiceMBean.repairAsync",
		"scheduled-task Gossiper.start: GossipTask",
		"scheduled-task Gossiper.start: sweep",
		"scheduled-task Gossiper.start: sweep #2",
		"stage-task Stage.GOSSIP Gossiper.sweep: markAlive",
		"background-task Gossiper.sweep: GOSSIP-LOOP (loop)",
		"java-main org.example.service.Daemon",
		"java-main org.example.tools.NodeTool",
	}
	for _, w := range want {
		if _, ok := have[w]; !ok {
			t.Errorf("missing %q", w)
		}
	}
	if len(got) != len(want) {
		t.Errorf("got %d entries, want %d:\n%s", len(got), len(want), strings.Join(keys, "\n"))
	}
	// False positives: comments, strings, text blocks, null handlers, Raw
	// statement builders, response messages, static interface helpers,
	// one-shot schedules, executor wrappers, non-static mains, tests,
	// examples and generated code.
	for _, k := range keys {
		for _, bad := range []string{"FAKE", "GHOST", "_TRACE", "Hidden", ".Raw", "ERROR", "Message.Request", "helper", "fakeInComment",
			"commented", "ScheduledThreadPoolExecutorPlus", "Helper", "DaemonTest", "HarnessMain", "Example", "GeneratedParser", "Fake"} {
			if strings.Contains(k, bad) {
				t.Errorf("unexpected entry %q", k)
			}
		}
	}
	checks := []struct {
		key         string
		file        string
		line, end   int
		via, detail string
	}{
		{"messaging-verb MUTATION_REQ", "src/org/example/net/Verb.java", 14, 0, "verb-enum", "handler MutationVerbHandler.instance"},
		{"messaging-verb OLD_RSP", "src/org/example/net/Verb.java", 19, 0, "verb-enum", "handler ResponseVerbHandler.instance"},
		{"verb-handler MutationVerbHandler.doVerb", "src/org/example/db/MutationVerbHandler.java", 10, 13, "doVerb", ""},
		{"verb-handler CounterVerbHandler", "src/org/example/db/CounterVerbHandler.java", 5, 10, "inherits-doVerb", "inherits doVerb from AbstractMutationVerbHandler"},
		{"native-message QUERY", "src/org/example/transport/QueryMessage.java", 8, 11, "message-request", "QueryMessage.execute"},
		{"cql-statement SelectStatement", "src/org/example/cql/SelectStatement.java", 6, 18, "cqlstatement", "execute L8, executeLocally L10"},
		{"cql-statement CreateTableStatement", "src/org/example/cql/CreateTableStatement.java", 3, 6, "cqlstatement", "inherits execute from AlterSchemaStatement"},
		{"cli-command nodetool repair_admin list", "src/org/example/tools/nodetool/RepairAdmin.java", 7, 11, "airline", ""},
		{"jmx-operation StorageServiceMBean.getLiveNodes", "src/org/example/service/StorageServiceMBean.java", 9, 9, "mbean-interface", "attribute"},
		{"jmx-operation StorageServiceMBean.forceKeyspaceCompaction", "src/org/example/service/StorageServiceMBean.java", 15, 15, "mbean-interface", "operation"},
		{"jmx-operation StorageServiceMBean.getTokenToEndpointMap", "src/org/example/service/StorageServiceMBean.java", 20, 20, "mbean-interface", "operation"},
		{"scheduled-task Gossiper.start: GossipTask", "src/org/example/service/Gossiper.java", 17, 0, "scheduleWithFixedDelay", "ScheduledExecutors.scheduledTasks.scheduleWithFixedDelay"},
		{"java-main org.example.service.Daemon", "src/org/example/service/Daemon.java", 5, 8, "main-method+script", "bin/daemon"},
	}
	for _, c := range checks {
		e := have[c.key]
		if e.File != c.file || e.Line != c.line || e.EndLine != c.end || e.Via != c.via || e.Detail != c.detail {
			t.Errorf("%s = %+v, want file %s line %d-%d via %s detail %q", c.key, e, c.file, c.line, c.end, c.via, c.detail)
		}
	}
}

func TestScanLangs(t *testing.T) {
	kinds := func(opt Options) map[string]bool {
		got, err := Scan("../testdata/inventory", opt)
		if err != nil {
			t.Fatal(err)
		}
		m := map[string]bool{}
		for _, e := range got {
			m[e.Kind] = true
		}
		return m
	}
	auto := kinds(Options{})
	for _, k := range []string{KindHTTP, KindNext, KindPyCLI, KindVerb, KindJavaMain} {
		if !auto[k] {
			t.Errorf("auto-detect should find %s entries", k)
		}
	}
	java := kinds(Options{Langs: []string{"java"}})
	for _, k := range []string{KindHTTP, KindWorkflow, KindNext, KindTRPC, KindPyCLI} {
		if java[k] {
			t.Errorf("--lang java should not scan %s", k)
		}
	}
	if !java[KindVerb] || !java[KindCLI] {
		t.Errorf("--lang java kinds = %v", java)
	}
	if goOnly := kinds(Options{Langs: []string{"go"}}); goOnly[KindVerb] || goOnly[KindNext] || !goOnly[KindHTTP] {
		t.Errorf("--lang go kinds = %v", goOnly)
	}
}

func TestJlex(t *testing.T) {
	src := "a /* b { */ \"c // d\" 'e' // f {\n\"\"\"\n g \\\"\"\" h\n\"\"\" i -> j :: k >> l >= m\n"
	var got []string
	for _, tk := range jlex([]byte(src)) {
		got = append(got, string(tk.k)+":"+tk.s)
	}
	want := "i:a s:c // d c:e s:\n g \\\"\"\" h\n i:i p:-> i:j p::: i:k p:> p:> i:l p:> p:= i:m"
	if strings.Join(got, " ") != want {
		t.Errorf("jlex =\n%s\nwant\n%s", strings.Join(got, " "), want)
	}
	toks := jlex([]byte(src))
	if toks[len(toks)-1].line != 4 {
		t.Errorf("last token line = %d, want 4", toks[len(toks)-1].line)
	}
}
