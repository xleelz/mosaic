import sys, re
import os
HERE = os.path.dirname(os.path.abspath(__file__)) + '/'
P = sys.argv[1]
src = open(P).read()

def block_span(text, header):
    """span of a top-level list item starting with header line (exact)"""
    i = text.index('\n' + header + '\n') + 1
    m = re.compile(r'\n(- |[a-z_]+:\n)').search(text, i + len(header))
    return i, m.start() + 1

def iface_span(text, comp, name):
    pat = '\n- component: %s\n  name: %s\n' % (comp, name)
    assert text.count(pat) == 1, (comp, name, text.count(pat))
    i = text.index(pat) + 1
    m = re.compile(r'\n(- |[a-z_]+:\n)').search(text, i + len(pat))
    return i, m.start() + 1

def replace_iface(text, comp, name, new):
    i, j = iface_span(text, comp, name)
    return text[:i] + new.strip('\n') + '\n' + text[j:]

def sub_in_iface(text, comp, name, old, new):
    i, j = iface_span(text, comp, name)
    blk = text[i:j]
    assert blk.count(old) == 1, (comp, name, old[:60])
    return text[:i] + blk.replace(old, new) + text[j:]

def sub_in_comp(text, cid, old, new):
    i, j = block_span(text, '- id: ' + cid)
    blk = text[i:j]
    assert blk.count(old) == 1, (cid, old[:60])
    return text[:i] + blk.replace(old, new) + text[j:]

def sub_once(text, old, new):
    assert text.count(old) == 1, old[:80]
    return text.replace(old, new)

def insert_before_section(text, section, add):
    k = text.index('\n' + section + ':\n') + 1
    return text[:k] + add.strip('\n') + '\n' + text[k:]

import importlib.util
spec = importlib.util.spec_from_file_location('parts', HERE + 'parts.py')
parts = importlib.util.module_from_spec(spec); spec.loader.exec_module(parts)
src = parts.apply(src, globals())
open(P, 'w').write(src)
print('ok')
