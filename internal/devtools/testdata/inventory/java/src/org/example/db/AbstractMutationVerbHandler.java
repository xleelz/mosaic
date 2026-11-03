package org.example.db;

import org.example.net.IVerbHandler;
import org.example.net.Message;

public abstract class AbstractMutationVerbHandler<T> implements IVerbHandler<T>
{
    public void doVerb(Message<T> message)
    {
        applyMutation(message);
    }

    abstract void applyMutation(Message<T> message);
}
