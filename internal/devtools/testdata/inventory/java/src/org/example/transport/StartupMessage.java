package org.example.transport;

import org.example.transport.Message.Request;

public class StartupMessage extends Request
{
    public static final Codec<StartupMessage> codec = null;

    protected Message.Response execute(Object state) { return null; }
}
