package org.example.db;

import org.example.net.Message;

public class CounterVerbHandler extends AbstractMutationVerbHandler<Counter>
{
    public static final CounterVerbHandler instance = new CounterVerbHandler();

    void applyMutation(Message<Counter> message) {}
}
