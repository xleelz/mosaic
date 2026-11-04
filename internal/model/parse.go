package model

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"

	yaml "go.yaml.in/yaml/v3"
)

// ToJSON converts YAML or JSON input to JSON. JSON passes through unchanged.
func ToJSON(data []byte) ([]byte, error) {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) > 0 && (trimmed[0] == '{' || trimmed[0] == '[') {
		return trimmed, nil
	}
	// YAML 1.2 (yaml.v3): only true/false are booleans, so keys and values
	// such as on, off, yes, no, y and n stay strings, and dates keep their text.
	var n yaml.Node
	if err := yaml.Unmarshal(data, &n); err != nil {
		return nil, fmt.Errorf("invalid YAML: %w", err)
	}
	v, err := fromNode(&n, 0)
	if err != nil {
		return nil, fmt.Errorf("invalid YAML: %w", err)
	}
	return json.Marshal(v)
}

// fromNode converts a YAML node to JSON-compatible values.
func fromNode(n *yaml.Node, depth int) (any, error) {
	if depth > 200 {
		return nil, fmt.Errorf("nesting too deep")
	}
	switch n.Kind {
	case 0:
		return nil, nil
	case yaml.DocumentNode:
		if len(n.Content) == 0 {
			return nil, nil
		}
		return fromNode(n.Content[0], depth+1)
	case yaml.AliasNode:
		return fromNode(n.Alias, depth+1)
	case yaml.SequenceNode:
		out := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := fromNode(c, depth+1)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
		return out, nil
	case yaml.MappingNode:
		out := make(map[string]any, len(n.Content)/2)
		for i := 0; i+1 < len(n.Content); i += 2 {
			v, err := fromNode(n.Content[i+1], depth+1)
			if err != nil {
				return nil, err
			}
			out[n.Content[i].Value] = v
		}
		return out, nil
	}
	switch n.ShortTag() {
	case "!!null":
		return nil, nil
	case "!!bool":
		return strconv.ParseBool(strings.ToLower(n.Value))
	case "!!int":
		lit := strings.ReplaceAll(n.Value, "_", "")
		if i, err := strconv.ParseInt(lit, 0, 64); err == nil {
			return i, nil
		}
		if u, err := strconv.ParseUint(strings.TrimPrefix(lit, "+"), 0, 64); err == nil {
			return json.Number(strconv.FormatUint(u, 10)), nil // a uint64 (behavior-language §30)
		}
		return json.Number(lit), nil
	case "!!float":
		if wholeLiteral(n.Value) {
			// yaml.v3 tags a whole number beyond uint64 as a float; keep
			// its digits (behavior-language §30: it becomes a double later,
			// with a warning).
			return json.Number(strings.TrimPrefix(n.Value, "+")), nil
		}
		f, err := strconv.ParseFloat(n.Value, 64)
		if err != nil || math.IsInf(f, 0) || math.IsNaN(f) {
			return nil, fmt.Errorf("line %d: unsupported number %q", n.Line, n.Value)
		}
		return f, nil
	}
	return n.Value, nil
}

// wholeLiteral reports whether s is a decimal integer literal beyond
// int64: an optional sign and digits, without a leading zero.
func wholeLiteral(s string) bool {
	s = strings.TrimPrefix(strings.TrimPrefix(s, "-"), "+")
	if len(s) < 19 || s[0] == '0' {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// ParseDocument strictly parses a YAML or JSON ontology document.
func ParseDocument(data []byte) (*Document, error) {
	js, err := ToJSON(data)
	if err != nil {
		return nil, err
	}
	var d Document
	if err := Decode(js, &d); err != nil {
		return nil, fmt.Errorf("invalid document: %w", err)
	}
	if d.SchemaVersion == 0 {
		d.SchemaVersion = SchemaVersion
	}
	for i := range d.Interfaces {
		d.Interfaces[i].Normalize()
	}
	d.EnsureSlices()
	return &d, nil
}
