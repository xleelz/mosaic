def _addfill(steps):
    for st in steps or []:
        if isinstance(st, dict):
            if 'call' in st and 'input' in st and isinstance(st['input'], dict):
                st.setdefault('fill', True)
            for k in ('then', 'else', 'steps', 'on_error'):
                if isinstance(st.get(k), list):
                    _addfill(st[k])
            if isinstance(st.get('options'), dict):
                for v in st['options'].values():
                    _addfill(v)
for i in interfaces:
    _addfill(i.get('behavior'))
