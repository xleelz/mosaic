package org.example.cql;

abstract public class AlterSchemaStatement implements CQLStatement.SingleKeyspaceCqlStatement
{
    public Object execute(Object state) { return apply(); }

    abstract Object apply();

    public String keyspace() { return "ks"; }
}
