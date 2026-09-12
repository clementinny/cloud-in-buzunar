package ro.cloudinbuzunar.monitor;

final class ServerHealthTracker {
    enum Event {
        NONE,
        DOWN,
        RECOVERED
    }

    private final int failureThreshold;
    private int consecutiveFailures;
    private boolean offline;

    ServerHealthTracker(
        int failureThreshold,
        int consecutiveFailures,
        boolean offline
    ) {
        this.failureThreshold = Math.max(1, failureThreshold);
        this.consecutiveFailures = Math.max(0, consecutiveFailures);
        this.offline = offline;
    }

    synchronized Event recordSuccess() {
        boolean wasOffline = offline;
        consecutiveFailures = 0;
        offline = false;
        return wasOffline ? Event.RECOVERED : Event.NONE;
    }

    synchronized Event recordFailure() {
        consecutiveFailures++;

        if (!offline && consecutiveFailures >= failureThreshold) {
            offline = true;
            return Event.DOWN;
        }

        return Event.NONE;
    }

    synchronized int consecutiveFailures() {
        return consecutiveFailures;
    }

    synchronized boolean offline() {
        return offline;
    }
}
