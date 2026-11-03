s = scs['remote-server-connect-refused']
s['expect'][0] = "steps.badver.result.error.code == 'connection-error' && calls['remote-agent-connection.do-connect-remote-agent-management'] == 5"
s['description'] = 'A version mismatch is retried like any other error: 5 attempts, then a permanent failure (remoteAgentConnection.ts:440-457).'
s = scs['remote-server-handshake-refusals']
s['state']['remote-extension-host-agent-server@srv1']['has_vsda'] = True
