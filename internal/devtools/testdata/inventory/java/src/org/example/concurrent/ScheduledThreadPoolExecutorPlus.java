package org.example.concurrent;

public class ScheduledThreadPoolExecutorPlus extends java.util.concurrent.ScheduledThreadPoolExecutor
{
    @Override
    public java.util.concurrent.ScheduledFuture<?> scheduleAtFixedRate(Runnable task, long initialDelay, long period, java.util.concurrent.TimeUnit unit)
    {
        return super.scheduleAtFixedRate(task, initialDelay, period, unit);
    }

    public java.util.concurrent.ScheduledFuture<?> scheduleWithFixedDelay(Runnable task, long initialDelay, long delay, java.util.concurrent.TimeUnit unit)
    {
        return delegate.scheduleWithFixedDelay(task, initialDelay, delay, unit);
    }
}
