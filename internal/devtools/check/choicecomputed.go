package main

// The choice-for-computed lint (DESIGN §13.1 item 33): a choice point whose
// branch the code computes from config, a flag, stored state or a policy
// engine, so the model should compute it too (batch's gate flag, the Cedar
// verdict, the fabric gate). Also the profile fields the round-4 lints read.

import (
	"fmt"
	"io"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/xleelz/mosaic/internal/model"
)

// lintProfile is what the round-4 lints read from a generation profile:
// naming.state_fields (racy transitions) and config.sources and
// config.required (choice-for-computed).
type lintProfile struct {
	Naming struct {
		StateFields []string `yaml:"state_fields"`
	} `yaml:"naming"`
	Config struct {
		Sources []struct {
			Path   string `yaml:"path"`
			Role   string `yaml:"role"`
			Format string `yaml:"format"`
		} `yaml:"sources"`
		Required []struct {
			Key string `yaml:"key"`
		} `yaml:"required"`
	} `yaml:"config"`
}

func loadLintProfile(file string) (*lintProfile, error) {
	p := &lintProfile{}
	if file == "" {
		return p, nil
	}
	b, err := os.ReadFile(file)
	if err != nil {
		return nil, err
	}
	if err := yaml.Unmarshal(b, p); err != nil {
		return nil, fmt.Errorf("%s: %w", file, err)
	}
	return p, nil
}

// stateFields are the state-machine fields a racy transition sets.
func (p *lintProfile) stateFields() map[string]bool {
	out := map[string]bool{"status": true, "state": true, "phase": true, "lifecycle": true}
	if p != nil {
		for _, f := range p.Naming.StateFields {
			out[strings.ToLower(strings.TrimSpace(f))] = true
		}
	}
	return out
}

var (
	pathGlob = regexp.MustCompile(`[A-Za-z0-9_.*{}\-]+(?:/[A-Za-z0-9_.*{}\-]+)+|[A-Za-z0-9_\-*]+\.[A-Za-z0-9]+`)
	// configRead matches code that reads config or a flag: environment
	// lookups, config and settings objects, feature flags and toggles.
	configRead = regexp.MustCompile(`(?i)\b(getenv|os\.environ|process\.env|envx\.|lookupenv|environ\b|cfg\.|conf\.|config\.|configuration|settings?\.|getsetting|getconfig|flags?\.|featureflag|feature_?flag|\bfeature\b|orgfeature|isenabled|is_enabled|enabled\(|launchdarkly|posthog\.isfeature|growthbook|unleash|databasedescriptor|systemproperty|getproperty)`)
	// policyRead matches code that asks a policy engine for a verdict.
	policyRead = regexp.MustCompile(`(?i)\b(cedar|isauthorized|is_authorized|authorizer|opa\b|rego\b|policy|policies|evaluatepolicy|entitle)`)
	// choiceWords are names and narration of a choice that say its branch
	// is config, a flag or a policy verdict.
	choiceWords = regexp.MustCompile(`(?i)(^|[^a-z])(flag|flags|feature|features|toggle|policy|policies|cedar|entitlement|entitled)([^a-z]|$)`)
	// configWords are weaker: config is also loaded from files and the
	// network, which can really fail.
	configWords = regexp.MustCompile(`(?i)(^|[^a-z])(config|configs|configured|configuration|setting|settings|env|envvar)([^a-z]|$)`)
	// outcomeWords are options naming an outcome the code doesn't decide:
	// a timeout, an error, a lost or slow peer.
	outcomeWords = regexp.MustCompile(`(?i)(^|[^a-z])(timeout|timed|error|errors|fail|fails|failed|failure|unreachable|down|lost|crash|crashed|slow|late|refused|reset|dropped)([^a-z]|$)`)
	// ioCall is cited code that waits on the network or chance.
	ioCall = regexp.MustCompile(`\b(Lookup[A-Za-z]*\(|Resolver\b|Dial[A-Za-z]*\(|http\.(Get|Post|Head|Do)\(|\.Do\(req|fetch\(|rand\.|Math\.random|time\.After\(|dialogService|showQuickPick|showInputBox|quickInputService|\.confirm\(|\.prompt\(|show(Warning|Information|Error)Message\()`)
	// policyWords in a choice's narration name a policy engine's verdict.
	policyWords = regexp.MustCompile(`(?i)(^|[^a-z])(cedar|opa|rego|policy engine|policies)([^a-z]|$)`)
	// userWords are options and choice ids that are a person's answer: a
	// dialog, a quick pick, a prompt. The code really doesn't decide those.
	userWords = regexp.MustCompile(`(?i)(^|[^a-z])(cancel|canceled|cancelled|dismiss|dismissed|decline|declined|confirm|confirms|confirmed|accept|pick|picker|prompt|dialog|user|input|answer|choose|action|menu|button|click)([^a-z]|$)`)
)

// configFiles are the code paths the profile's config.sources name: a
// cited file matching one reads config.
func (p *lintProfile) configFiles() []string {
	var out []string
	if p == nil {
		return out
	}
	for _, s := range p.Config.Sources {
		for _, m := range pathGlob.FindAllString(s.Path, -1) {
			if strings.Contains(m, "/") || strings.Contains(m, "*") || strings.Contains(m, ".") {
				out = append(out, m)
			}
		}
	}
	return out
}

func matchesConfigFile(file string, globs []string) bool {
	for _, g := range globs {
		if g == file || strings.HasSuffix(file, "/"+g) {
			return true
		}
		if ok, _ := path.Match(g, file); ok {
			return true
		}
		if !strings.Contains(g, "/") {
			if ok, _ := path.Match(g, path.Base(file)); ok {
				return true
			}
		}
		if strings.HasSuffix(g, "/") || !strings.ContainsAny(path.Base(g), ".*") {
			if strings.HasPrefix(file, strings.TrimSuffix(g, "/")+"/") {
				return true
			}
		}
	}
	return false
}

func normWords(s string) string {
	return strings.Map(func(r rune) rune {
		switch {
		case r >= 'A' && r <= 'Z':
			return r + 'a' - 'A'
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9':
			return r
		}
		return -1
	}, s)
}

// choiceSite is one choice point.
type choiceSite struct {
	path string
	step model.Step
}

func choiceSites(i *model.Interface) []choiceSite {
	var out []choiceSite
	for _, sp := range behaviorPaths(i) {
		if sp.Step.Choice != "" {
			out = append(out, choiceSite{sp.Path, sp.Step})
		}
	}
	return out
}

// choiceOK reports an exemption: attributes.choice_ok on the interface or
// its component, a reason string or a map of choice id to reason.
func choiceOK(attrs map[string]any, choice string) bool {
	switch v := attrs["choice_ok"].(type) {
	case string:
		return strings.TrimSpace(v) != ""
	case map[string]any:
		return str(v[choice]) != ""
	}
	return false
}

// codeLines returns the cited lines of one source (the whole cited range,
// or the cited line alone), or nil.
func codeLines(root *codeRoot, s model.Source) (string, []string) {
	if root == nil || s.Path == "" || isPacked(s) {
		return "", nil
	}
	p := normPath(s.Path)
	if st, _ := root.resolve(model.Source{Path: p}); st != citeOK {
		return p, nil
	}
	lines := root.file(p)
	if s.Line <= 0 || s.Line > len(lines) {
		return p, nil
	}
	end := s.EndLine
	if end < s.Line {
		end = s.Line
	}
	end = min(end, len(lines), s.Line+40)
	return p, lines[s.Line-1 : end]
}

// lintChoiceForComputed lists the choice points of owned, non-boundary
// interfaces whose branch the code computes: the choice's options or id name
// a config or flag id, its narration says it is a flag, config or policy
// verdict, or (with --code) its cited lines read config, a flag or a policy
// engine. attributes.choice_ok exempts nondeterminism the code really has.
func lintChoiceForComputed(doc *model.Document, origins map[string]string, prof *lintProfile, root *codeRoot) *integrityReport {
	x := indexed(doc)
	cfgNames := map[string]string{} // normalized name -> config id
	for _, c := range doc.Configs {
		cfgNames[normWords(c.ID)] = c.ID
		if k := str(c.Attributes["key"]); k != "" {
			cfgNames[normWords(k)] = c.ID
		}
	}
	var keys []string
	if prof != nil {
		for _, k := range prof.Config.Required {
			if n := normWords(k.Key); len(n) >= 4 && !strings.Contains(k.Key, " ") {
				cfgNames[n] = k.Key
				keys = append(keys, k.Key)
			}
		}
	}
	files := prof.configFiles()
	r := &integrityReport{Lint: "choice-for-computed", Unit: "choice points"}
	sc := shareCounter{}
	for _, id := range sortedIfaces(x) {
		i := x.Interfaces[id]
		if len(i.Behavior) == 0 || !owned(i.Attributes) {
			continue
		}
		frag := origins[model.KindInterface+"/"+id]
		c := x.Components[i.Component]
		for _, cs := range choiceSites(i) {
			s := cs.step
			if choiceOK(i.Attributes, s.Choice) || choiceOK(componentAttrs(c), s.Choice) {
				sc.add(frag, false)
				continue
			}
			var why, weak []string
			// The choice's id or options name a config or flag id.
			names := []string{s.Choice}
			for o := range s.Options {
				names = append(names, o)
			}
			sort.Strings(names[1:])
			outcome := false
			for k, n := range names {
				n = strings.ReplaceAll(n, "_", " ")
				if k > 0 && outcomeWords.MatchString(n) || userWords.MatchString(n) {
					outcome = true
				}
			}
			for _, n := range names {
				if cid, ok := cfgNames[normWords(n)]; ok && len(normWords(n)) >= 4 {
					why = append(why, fmt.Sprintf("%q names config %s", n, cid))
					break
				}
			}
			for _, n := range names {
				if m := choiceWords.FindStringSubmatch(strings.ReplaceAll(n, "_", " ")); m != nil {
					why = append(why, fmt.Sprintf("%q says %s", n, strings.ToLower(m[2])))
					break
				}
				if m := configWords.FindStringSubmatch(strings.ReplaceAll(n, "_", " ")); m != nil {
					weak = append(weak, fmt.Sprintf("%q says %s", n, strings.ToLower(m[2])))
					break
				}
			}
			// Toggle options: on/off, enabled/disabled.
			if len(s.Options) == 2 {
				_, on := s.Options["on"]
				_, off := s.Options["off"]
				_, en := s.Options["enabled"]
				_, dis := s.Options["disabled"]
				if on && off || en && dis {
					weak = append(weak, "its options are a toggle")
				}
			}
			// Its narration says so.
			text := s.Title + " " + s.Detail
			if m := policyWords.FindStringSubmatch(text); m != nil {
				why = append(why, fmt.Sprintf("its title says %q", strings.ToLower(m[2])))
			} else if m := configWords.FindStringSubmatch(text); m != nil {
				weak = append(weak, fmt.Sprintf("its title says %q", strings.ToLower(m[2])))
			}
			// Its cited code reads config, a flag or a policy engine.
			if s.Source != nil {
				p, lines := codeLines(root, *s.Source)
				code := strings.Join(lines, "\n")
				if ioCall.MatchString(code) {
					outcome = true
				}
				switch {
				case p != "" && matchesConfigFile(p, files):
					weak = append(weak, "it cites a config source ("+p+")")
				case len(lines) > 0:
					hit := ""
					if m := configRead.FindString(code); m != "" {
						hit = "reads config or a flag (" + m + ")"
					} else if m := policyRead.FindString(code); m != "" {
						hit = "asks a policy engine (" + m + ")"
					} else {
						for _, k := range keys {
							if strings.Contains(code, k) {
								hit = "reads " + k
								break
							}
						}
					}
					if hit != "" {
						weak = append(weak, fmt.Sprintf("the cited %s %s", s.Source.String(), hit))
					}
				}
			}
			// Weak signals count unless the options or the cited code name
			// an outcome the code doesn't decide (a timeout, a failed load,
			// a DNS answer).
			if len(why) > 0 || !outcome {
				why = append(why, weak...)
			}
			if len(why) == 0 {
				sc.add(frag, false)
				continue
			}
			sc.add(frag, true)
			at := cs.path
			if _, rest, ok := strings.Cut(at, ":"); ok {
				at = rest
			}
			r.Findings = append(r.Findings, integrityFinding{"choice-for-computed", frag, id + "." + s.Choice,
				fmt.Sprintf("choice at %s looks computed from config, a flag, stored state or a policy (%s); fix: compute the branch from config, fixture state or the policy's inputs, or attributes.choice_ok: \"<reason>\" for nondeterminism the code really has", at, strings.Join(why, "; "))})
		}
	}
	r.finish(sc)
	return r
}

// printCount prints a report gated on its finding count (--max-<lint> N):
// the share lines without a share gate, then the count against N.
func (r *integrityReport) printCount(w io.Writer, max int, quiet bool) bool {
	r.print(w, -1, quiet)
	if max < 0 {
		return false
	}
	over := len(r.Findings) > max
	mark := " "
	if over {
		mark = "✗"
	}
	fmt.Fprintf(w, "%s --max-%s %d: %d findings\n", mark, r.Lint, max, len(r.Findings))
	return over
}
