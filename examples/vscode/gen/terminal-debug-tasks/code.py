import re, os
ROOT='/home/lbethay/.cache/mosaic-bench/vscode-1.144.0'
_cache={}
def lines(f):
    if f not in _cache:
        _cache[f]=open(os.path.join(ROOT,f)).read().split('\n')
    return _cache[f]
def match_end(f, line):
    """from 1-based line, find first opening bracket and return line of its match"""
    L=lines(f); depth=0; started=False
    i=line-1
    while i < len(L):
        s=L[i]
        # strip strings roughly
        s2=re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`","''",s)
        s2=re.sub(r'//.*$','',s2)
        for ch in s2:
            if ch in '({[': depth+=1; started=True
            elif ch in ')}]':
                depth-=1
                if started and depth==0: return i+1
        i+=1
    return line
def find(f, pat, start=1, end=None):
    L=lines(f); r=re.compile(pat)
    for i in range(start-1, len(L) if end is None else end):
        if r.search(L[i]): return i+1
    return None
def cls(f, name):
    l=find(f, r'^(export )?(abstract )?class %s\b'%re.escape(name))
    return (l, match_end(f,l)) if l else None
def find_class_any(name, files):
    for f in files:
        try:
            r=cls(f,name)
        except FileNotFoundError: continue
        if r: return f,r
    return None
def method(f, name, start=1, end=None):
    l=find(f, r'^\s*(public |private |protected |static |override |readonly )*(async )?\*?%s\s*(<[^>]*>)?\('%re.escape(name), start, end)
    if not l: return None
    # find the line with '{' starting body
    return (l, match_end_body(f,l))
def match_end_body(f,l):
    L=lines(f); depth=0; started=False; paren=0
    i=l-1
    while i<len(L):
        s=re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`","''",L[i]); s=re.sub(r'//.*$','',s)
        for ch in s:
            if ch=='(': paren+=1
            elif ch==')': paren-=1
            elif ch=='{' and paren==0: depth+=1; started=True
            elif ch=='}' and paren==0 and started:
                depth-=1
                if depth==0: return i+1
        i+=1
    return l
