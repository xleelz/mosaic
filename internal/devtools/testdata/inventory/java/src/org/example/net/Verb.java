package org.example.net;

import java.util.function.Supplier;

import org.example.db.MutationVerbHandler;
import org.example.db.CounterVerbHandler;

/**
 * Messaging verbs. FAKE_REQ (9, () -> FakeVerbHandler.instance) in a comment is not a verb.
 */
public enum Verb
{
    MUTATION_RSP (60, () -> ResponseVerbHandler.instance),
    MUTATION_REQ (0,  () -> Mutation.serializer, () -> MutationVerbHandler.instance, MUTATION_RSP),
    // a comment between constants: GHOST_REQ (1, () -> null),
    COUNTER_REQ  (24, () -> Mutation.serializer, () -> CounterVerbHandler.instance, MUTATION_RSP),
    /** @deprecated */
    @Deprecated(since = "4.0")
    OLD_RSP      (4,  () -> null, () -> ResponseVerbHandler.instance),
    _TRACE       (30, () -> Mutation.serializer, () -> null),
    ;

    private final Supplier<? extends IVerbHandler<?>> handler;

    Verb(int id, Supplier<?>... suppliers)
    {
        this.handler = null;
        String s = "scheduleWithFixedDelay(new Fake(), 1, 1, null)"; // a string, not a call
        char c = '{';
    }
}
