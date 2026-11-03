package model_test

import (
	"strings"
	"testing"

	"github.com/xleelz/mosaic/internal/model"
)

// TestImportedTopicsPrefixed: §17 item 8. An imported document's topics
// take its as: prefix (an interface-id topic follows its component), the
// importer subscribes to <as>/<topic>, and a substrate checked alone gets
// no no-subscriber warning, while an importer still does.
func TestImportedTopicsPrefixed(t *testing.T) {
	bus, err := model.ParseDocument([]byte(`
id: bus
level: service
components: [{id: broker}]
interfaces:
  - {component: broker, name: send, behavior: [{publish: bus-message, input: {}}, {publish: broker.send, input: {}}]}
  - {component: broker, name: echo, subscribe: [bus-message, broker.send]}
`))
	if err != nil {
		t.Fatal(err)
	}
	for _, is := range model.Validate(bus) {
		if strings.Contains(is.Message, "subscribes") {
			t.Errorf("substrate alone: %s: %s", is.Path, is.Message)
		}
	}
	app, err := model.ParseDocument([]byte(`
id: app
level: system
imports: [{ontology: bus, as: q}]
components: [{id: app}]
interfaces:
  - {component: app, name: on-message, subscribe: [q/bus-message]}
  - {component: app, name: loud, behavior: [{publish: nobody-listens, input: {}}]}
`))
	if err != nil {
		t.Fatal(err)
	}
	m, err := model.MergeImports(app, map[string]*model.Document{"bus": bus})
	if err != nil {
		t.Fatal(err)
	}
	x := model.NewIndex(m)
	send := x.Interfaces["q/broker.send"]
	if send == nil || send.Behavior[0].Publish != "q/bus-message" || send.Behavior[1].Publish != "q/broker.send" {
		t.Fatalf("publish topics not prefixed: %+v", send)
	}
	if got := x.Interfaces["q/broker.echo"].Subscribe; len(got) != 2 || got[0] != "q/bus-message" || got[1] != "q/broker.send" {
		t.Errorf("subscription not prefixed: %v", got)
	}
	if subs := strings.Join(x.Subscribers["q/bus-message"], ","); subs != "app.on-message,q/broker.echo" && subs != "q/broker.echo,app.on-message" {
		t.Errorf("subscribers of q/bus-message: %q", subs)
	}
	var warned []string
	for _, is := range model.Validate(m) {
		if is.Severity == model.SeverityError {
			t.Errorf("merged: %s: %s", is.Path, is.Message)
		}
		if strings.Contains(is.Message, "subscribes") {
			warned = append(warned, is.Path)
		}
	}
	if len(warned) != 1 || !strings.Contains(warned[0], "app.loud") {
		t.Errorf("no-subscriber warnings in the importer: %v", warned)
	}
}
