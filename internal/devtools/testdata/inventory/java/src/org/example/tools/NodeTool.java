package org.example.tools;

import java.util.List;

import io.airlift.airline.Cli;
import org.example.tools.nodetool.*;

public class NodeTool
{
    public static void main(String... args)
    {
        List<Class<? extends Runnable>> commands = List.of(Status.class, Help.class);
        Cli.CliBuilder<Runnable> builder = Cli.builder("nodetool");
        builder.withCommands(commands);
        builder.withGroup("repair_admin")
               .withDefaultCommand(RepairAdmin.ListCmd.class)
               .withCommand(RepairAdmin.ListCmd.class);
    }
}
