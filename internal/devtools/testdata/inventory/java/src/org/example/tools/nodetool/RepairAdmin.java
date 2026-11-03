package org.example.tools.nodetool;

import io.airlift.airline.Command;

public abstract class RepairAdmin implements Runnable
{
    @Command(name = "list", description = "list repair sessions")
    public static class ListCmd extends RepairAdmin
    {
        public void run() { }
    }
}
