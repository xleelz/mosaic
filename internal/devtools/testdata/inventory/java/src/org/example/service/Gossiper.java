package org.example.service;

import java.util.concurrent.TimeUnit;

import org.example.concurrent.ScheduledExecutors;
import org.example.concurrent.Stage;

public class Gossiper
{
    private class GossipTask implements Runnable
    {
        public void run() { }
    }

    public void start()
    {
        ScheduledExecutors.scheduledTasks.scheduleWithFixedDelay(new GossipTask(), 1000, 1000, TimeUnit.MILLISECONDS);
        ScheduledExecutors.optionalTasks.scheduleAtFixedRate(this::sweep, 1, 1, TimeUnit.MINUTES);
        ScheduledExecutors.optionalTasks.scheduleAtFixedRate(() -> sweep(), 2, 2, TimeUnit.MINUTES);
        // ScheduledExecutors.optionalTasks.scheduleAtFixedRate(this::commented, 1, 1, TimeUnit.MINUTES);
        ScheduledExecutors.optionalTasks.schedule(this::sweep, 1, TimeUnit.MINUTES); // one-shot: not recurring
    }

    void sweep()
    {
        Stage.GOSSIP.execute(() -> markAlive());
        executorFactory().infiniteLoop("GOSSIP-LOOP", this::loop, true);
    }

    void markAlive() { }
    void loop() { }
    static Object executorFactory() { return null; }
}
