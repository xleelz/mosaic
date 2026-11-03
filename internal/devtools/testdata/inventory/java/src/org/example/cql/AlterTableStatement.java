package org.example.cql;

public abstract class AlterTableStatement extends AlterSchemaStatement
{
    private static class AddColumns extends AlterTableStatement
    {
        Object apply() { return null; }
    }

    public static final class Raw extends CQLStatement.Raw
    {
        public CQLStatement prepare() { return new AddColumns(); }
    }
}
