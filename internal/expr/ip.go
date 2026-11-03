package expr

import (
	"net/netip"

	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/common/types/ref"
	"cel.dev/cel-go/common/types/traits"
)

// ipHelpers declares the §13.1 item 35 IP and CIDR helpers, for ipRanges,
// netguard policies and client-IP keys. Addresses are strings; ip(s)
// normalizes one (an IPv4-mapped IPv6 address becomes IPv4) and every
// helper fails on an invalid address or prefix. The predicates are Go's
// net/netip ones; ipIsLinkLocal is link-local unicast or multicast. All
// are pure, so the eval sandbox gets them too.
func ipHelpers() []cel.EnvOption {
	str, in, bl := cel.StringType, cel.IntType, cel.BoolType
	pred := func(name string, f func(netip.Addr) bool) cel.EnvOption {
		return cel.Function(name, cel.Overload(name+"_string", []*cel.Type{str}, bl, cel.UnaryBinding(func(v ref.Val) ref.Val {
			a, err := parseIP(v, name)
			if err != nil {
				return err
			}
			return types.Bool(f(a))
		})))
	}
	return []cel.EnvOption{
		cel.Function("ip",
			cel.Overload("ip_string", []*cel.Type{str}, str, cel.UnaryBinding(func(v ref.Val) ref.Val {
				a, err := parseIP(v, "ip")
				if err != nil {
					return err
				}
				return types.String(a.String())
			}))),
		cel.Function("ipFamily",
			cel.Overload("ipFamily_string", []*cel.Type{str}, in, cel.UnaryBinding(func(v ref.Val) ref.Val {
				a, err := parseIP(v, "ipFamily")
				if err != nil {
					return err
				}
				if a.Is4() {
					return types.Int(4)
				}
				return types.Int(6)
			}))),
		cel.Function("inCidr",
			cel.Overload("inCidr_string_string", []*cel.Type{str, str}, bl, cel.BinaryBinding(func(a, c ref.Val) ref.Val {
				addr, err := parseIP(a, "inCidr")
				if err != nil {
					return err
				}
				return inPrefix(addr, c, "inCidr")
			}))),
		cel.Function("inAnyCidr",
			cel.Overload("inAnyCidr_string_list", []*cel.Type{str, cel.ListType(cel.DynType)}, bl, cel.BinaryBinding(func(a, l ref.Val) ref.Val {
				addr, err := parseIP(a, "inAnyCidr")
				if err != nil {
					return err
				}
				list, ok := l.(traits.Lister)
				if !ok {
					return types.NewErr("inAnyCidr needs a list of CIDRs")
				}
				found := false
				for it := list.Iterator(); it.HasNext() == types.True; {
					r := inPrefix(addr, it.Next(), "inAnyCidr")
					if types.IsError(r) {
						return r
					}
					found = found || r == types.True
				}
				return types.Bool(found)
			}))),
		pred("ipIsLoopback", netip.Addr.IsLoopback),
		pred("ipIsPrivate", netip.Addr.IsPrivate),
		pred("ipIsLinkLocal", func(a netip.Addr) bool { return a.IsLinkLocalUnicast() || a.IsLinkLocalMulticast() }),
		pred("ipIsMulticast", netip.Addr.IsMulticast),
		pred("ipIsUnspecified", netip.Addr.IsUnspecified),
	}
}

// parseIP parses an address argument, unmapping an IPv4-mapped IPv6 one.
func parseIP(v ref.Val, fn string) (netip.Addr, ref.Val) {
	s, ok := v.(types.String)
	if !ok {
		return netip.Addr{}, types.NewErr("%s needs an IP address string, got %s", fn, v.Type().TypeName())
	}
	a, err := netip.ParseAddr(string(s))
	if err != nil {
		return netip.Addr{}, types.NewErr("%s: invalid IP address %q", fn, string(s))
	}
	return a.Unmap(), nil
}

// inPrefix reports whether addr is in the CIDR c. An IPv4-mapped IPv6
// prefix (::ffff:10.0.0.0/104) matches as its IPv4 form, as addresses do;
// an address and a prefix of different families never match.
func inPrefix(addr netip.Addr, c ref.Val, fn string) ref.Val {
	s, ok := c.(types.String)
	if !ok {
		return types.NewErr("%s needs a CIDR string, got %s", fn, c.Type().TypeName())
	}
	p, err := netip.ParsePrefix(string(s))
	if err != nil {
		return types.NewErr("%s: invalid CIDR %q", fn, string(s))
	}
	if pa := p.Addr(); pa.Is4In6() && p.Bits() >= 96 {
		p = netip.PrefixFrom(pa.Unmap(), p.Bits()-96)
	}
	return types.Bool(p.Masked().Contains(addr))
}
