get('flows', 'chat-submit')['tags'].append('feature:chat')
f = get('flows', 'inline-chat-start')
f.setdefault('tags', []).append('feature:inline-chat')
