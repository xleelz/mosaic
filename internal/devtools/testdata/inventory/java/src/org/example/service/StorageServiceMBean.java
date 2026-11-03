package org.example.service;

import java.util.List;
import java.util.Map;

public interface StorageServiceMBean
{
    /** Live nodes. void fakeInComment(); */
    public List<String> getLiveNodes();

    public void setCompactionThroughput(int value);

    public boolean isJoined();

    public void forceKeyspaceCompaction(boolean splitOutput, String keyspace, String... tables) throws java.io.IOException;

    public void forceKeyspaceCompaction(String keyspace);

    @Deprecated(since = "5.0")
    public Map<String, String> getTokenToEndpointMap(boolean withPort);

    static String helper() { return "not an operation"; }

    default void repairAsync(String keyspace) { }
}
