package org.example.tools.nodetool;

@io.airlift.airline.Command(name = "orphan", description = "not registered, named by its directory")
public class Unregistered implements Runnable
{
    public void run() { }
}
