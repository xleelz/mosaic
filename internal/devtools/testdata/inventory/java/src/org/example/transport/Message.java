package org.example.transport;

public abstract class Message
{
    public enum Type
    {
        ERROR   (0, Direction.RESPONSE, ErrorMessage.codec),
        QUERY   (7, Direction.REQUEST,  QueryMessage.codec),
        STARTUP (1, Direction.REQUEST,  StartupMessage.codec);

        Type(int opcode, Direction d, Codec<?> codec) {}
    }

    public static abstract class Request extends Message
    {
        protected abstract Response execute(Object state);

        public final Response execute(Object state, long time)
        {
            return execute(state);
        }
    }

    public static abstract class Response extends Message {}
}
