package org.example.db;

import org.example.net.Message;

public class MutationVerbHandler extends AbstractMutationVerbHandler<Mutation>
{
    public static final MutationVerbHandler instance = new MutationVerbHandler();

    @Override
    public void doVerb(Message<Mutation> message)
    {
        super.doVerb(message);
    }

    void applyMutation(Message<Mutation> message) {}
}
