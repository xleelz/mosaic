package org.example.db;

import org.example.net.IVerbHandler;

public class CleanupRequest
{
    public static IVerbHandler<CleanupRequest> createVerbHandler(Object ctx)
    {
        return in -> {
            System.out.println(in);
        };
    }

    public static final IVerbHandler<CleanupRequest> verbHandler = createVerbHandler(null);

    public static final IVerbHandler<CleanupRequest> inline = message -> { };

    static IVerbHandler<CleanupRequest> anonymous()
    {
        return new IVerbHandler<CleanupRequest>()
        {
            public void doVerb(org.example.net.Message<CleanupRequest> m) { }
        };
    }
}
