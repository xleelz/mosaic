package model

import "strings"

// Imported topics (§17 item 8). Topics published or subscribed inside an
// imported document take its as: prefix (<as>/<topic>), as its components
// do, so two imports of one substrate don't share a topic, and an importer
// subscribes to <as>/<topic>. MergeImports renames them.

// unprefixTopic strips a topic's import prefixes: each is a slug followed
// by "/". It returns s unchanged when a prefix isn't a slug.
func unprefixTopic(s string) string {
	i := strings.LastIndex(s, "/")
	if i < 0 {
		return s
	}
	for _, seg := range strings.Split(s[:i], "/") {
		if !ValidID(seg) {
			return s
		}
	}
	return s[i+1:]
}

// importTopic is a topic of a document imported as as: an interface id
// follows its component's renaming, and any other topic takes the prefix.
func importTopic(rn renamer, ifaces map[string]bool, as string) func(string) string {
	return func(t string) string {
		if ifaces[t] {
			return rn.iface(t)
		}
		if as == "" {
			return t
		}
		return as + "/" + t
	}
}

// importableAlone reports whether a document checked alone is one that
// others import: a document at a level (§14.2) with no imports of its own,
// as a substrate is. Its topics are for its importers, so a topic with no
// subscriber in it isn't a finding there (§17 item 8).
func importableAlone(d *Document) bool {
	return d != nil && d.Level != "" && len(d.Imports) == 0
}
