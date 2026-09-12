package ro.cloudinbuzunar.monitor;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class ServerHealthTrackerTest {
    @Test
    public void declaresDownOnlyAfterConfiguredFailures() {
        ServerHealthTracker tracker = new ServerHealthTracker(3, 0, false);

        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordFailure());
        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordFailure());
        assertEquals(ServerHealthTracker.Event.DOWN, tracker.recordFailure());
        assertTrue(tracker.offline());
        assertEquals(3, tracker.consecutiveFailures());
        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordFailure());
    }

    @Test
    public void notifiesRecoveryOnceAndResetsFailures() {
        ServerHealthTracker tracker = new ServerHealthTracker(2, 2, true);

        assertEquals(
            ServerHealthTracker.Event.RECOVERED,
            tracker.recordSuccess()
        );
        assertFalse(tracker.offline());
        assertEquals(0, tracker.consecutiveFailures());
        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordSuccess());
    }

    @Test
    public void successBeforeThresholdPreventsFalseAlarm() {
        ServerHealthTracker tracker = new ServerHealthTracker(3, 0, false);

        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordFailure());
        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordSuccess());
        assertEquals(ServerHealthTracker.Event.NONE, tracker.recordFailure());
        assertFalse(tracker.offline());
    }
}
