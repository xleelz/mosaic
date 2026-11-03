package org.example.net;

class ResponseVerbHandler implements IVerbHandler<Object>
{
    public static final ResponseVerbHandler instance = new ResponseVerbHandler();

    @Override
    public void doVerb(Message<Object> message)
    {
        String text = """
            { not a block: class Hidden implements IVerbHandler {
            """;
    }
}
