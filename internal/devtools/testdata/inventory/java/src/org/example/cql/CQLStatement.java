package org.example.cql;

public interface CQLStatement
{
    Object execute(Object state);

    default Object executeLocally(Object state) { return execute(state); }

    abstract class Raw
    {
        public abstract CQLStatement prepare();
    }

    interface SingleKeyspaceCqlStatement extends CQLStatement
    {
        String keyspace();
    }
}
