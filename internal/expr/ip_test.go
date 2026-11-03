package expr

import (
	"reflect"
	"strings"
	"testing"
)

func TestIPHelpers(t *testing.T) {
	act := map[string]any{"input": map[string]any{"peer": "::ffff:10.1.2.3"}}
	for src, want := range map[string]any{
		"ip('10.0.0.1')":                                              "10.0.0.1",
		"ip('::ffff:192.168.1.1')":                                    "192.168.1.1",
		"ip('2001:DB8::1')":                                           "2001:db8::1",
		"ip(input.peer)":                                              "10.1.2.3",
		"ipFamily('10.0.0.1')":                                        int64(4),
		"ipFamily('::1')":                                             int64(6),
		"ipFamily('::ffff:1.2.3.4')":                                  int64(4),
		"inCidr('10.1.2.3', '10.0.0.0/8')":                            true,
		"inCidr('11.1.2.3', '10.0.0.0/8')":                            false,
		"inCidr(input.peer, '10.1.0.0/16')":                           true,
		"inCidr('10.1.2.3', '10.1.2.9/24')":                           true, // the prefix is masked
		"inCidr('10.1.2.3', '::/0')":                                  false,
		"inCidr('10.1.2.3', '::ffff:10.0.0.0/104')":                   true,
		"inCidr('2001:db8::5', '2001:db8::/32')":                      true,
		"inAnyCidr('192.168.4.4', ['10.0.0.0/8', '192.168.0.0/16'])":  true,
		"inAnyCidr('8.8.8.8', ['10.0.0.0/8', '192.168.0.0/16'])":      false,
		"inAnyCidr('8.8.8.8', [])":                                    false,
		"ipIsLoopback('127.0.0.2')":                                   true,
		"ipIsLoopback('::1')":                                         true,
		"ipIsLoopback('::ffff:127.0.0.1')":                            true,
		"ipIsPrivate('172.16.0.1')":                                   true,
		"ipIsPrivate('fd00::1')":                                      true,
		"ipIsPrivate('8.8.8.8')":                                      false,
		"ipIsLinkLocal('169.254.169.254')":                            true,
		"ipIsLinkLocal('fe80::1')":                                    true,
		"ipIsLinkLocal('224.0.0.1')":                                  true,
		"ipIsLinkLocal('10.0.0.1')":                                   false,
		"ipIsMulticast('239.1.1.1')":                                  true,
		"ipIsMulticast('ff02::1')":                                    true,
		"ipIsUnspecified('0.0.0.0')":                                  true,
		"ipIsUnspecified('::')":                                       true,
		"ipIsUnspecified('1.1.1.1')":                                  false,
		"eval('inCidr(a, c)', {'a': '10.0.0.1', 'c': '10.0.0.0/24'})": true,
	} {
		got, err := Behavior.Eval(src, act)
		if err != nil {
			t.Errorf("%s: %v", src, err)
			continue
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: got %#v, want %#v", src, got, want)
		}
	}
	for src, msg := range map[string]string{
		"ip('300.1.1.1')":                            "invalid IP address",
		"ip('example.com')":                          "invalid IP address",
		"inCidr('10.0.0.1', '10.0.0.0/33')":          "invalid CIDR",
		"inCidr('nope', '10.0.0.0/8')":               "invalid IP address",
		"inAnyCidr('10.0.0.1', ['10.0.0.0/8', 'x'])": "invalid CIDR",
		"ipIsPrivate('')":                            "invalid IP address",
	} {
		_, err := Behavior.Eval(src, act)
		if err == nil || !strings.Contains(err.Error(), msg) {
			t.Errorf("%s: got %v, want an error with %q", src, err, msg)
		}
	}
}
