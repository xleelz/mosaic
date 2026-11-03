package org.example.transport;

public class QueryMessage extends Message.Request
{
    public static final Codec<QueryMessage> codec = null;

    @Override
    protected Message.Response execute(Object state)
    {
        return null;
    }
}
