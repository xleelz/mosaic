"""Apply citation corrections: (title fragment or '*', old source, new source)."""
import glob, re, sys
FIX = [l.split(' | ') for l in open(sys.argv[1]).read().strip().split('\n') if l.strip() and not l.startswith('#')]
for p in glob.glob('parts/*.yaml') + ['build.py']:
    s = open(p).read(); o = s
    for title, old, new in FIX:
        if title == '*':
            s = s.replace(f'"{old}"', f'"{new}"')
        else:
            # replace the source following a title containing the fragment
            pat = re.compile(r'(title: "?[^\n]*' + re.escape(title) + r'[^\n]*\n(?:[ \t]+[^\n]*\n){0,1}?[ \t]+source: )"' + re.escape(old) + '"')
            s, n = pat.subn(lambda m: m.group(1) + f'"{new}"', s)
            if n == 0:
                print('NOFIX', p, title, old) if old in s and p.endswith('.yaml') else None
    if s != o: open(p, 'w').write(s)
