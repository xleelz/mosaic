package org.example.net;

public interface IVerbHandler<T>
{
    void doVerb(Message<T> message) throws java.io.IOException;
}
