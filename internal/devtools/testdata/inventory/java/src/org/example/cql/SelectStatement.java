package org.example.cql;

import java.util.List;

@SuppressWarnings({"unchecked", "rawtypes"})
public class SelectStatement implements CQLStatement.SingleKeyspaceCqlStatement
{
    public Object execute(Object state) { return null; }

    public Object executeLocally(Object state) { return null; }

    public String keyspace() { return "ks"; }

    public static class Raw extends CQLStatement.Raw
    {
        public SelectStatement prepare() { return new SelectStatement(); }
    }
}
