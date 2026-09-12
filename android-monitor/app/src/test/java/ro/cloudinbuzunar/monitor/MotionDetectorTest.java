package ro.cloudinbuzunar.monitor;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class MotionDetectorTest {
    @Test
    public void ignoresCalibrationAndSmallSensorNoise() {
        MotionDetector detector = calibratedDetector();

        assertTrue(Float.isNaN(detector.sample(0.2f, 0.1f, 9.7f, 3000)));
        assertTrue(Float.isNaN(detector.sample(-0.1f, 0.2f, 9.8f, 3200)));
    }

    @Test
    public void triggersAfterTwoLargeChangesAndThenUsesCooldown() {
        MotionDetector detector = calibratedDetector();

        assertTrue(Float.isNaN(detector.sample(3.0f, 0f, 9.8f, 3000)));
        float first = detector.sample(3.2f, 0f, 9.8f, 3100);
        assertFalse(Float.isNaN(first));

        assertTrue(Float.isNaN(detector.sample(0f, 3.2f, 9.8f, 4000)));
        assertTrue(Float.isNaN(detector.sample(0f, 3.3f, 9.8f, 4100)));

        assertTrue(Float.isNaN(detector.sample(0f, 3.2f, 9.8f, 124000)));
        assertFalse(Float.isNaN(detector.sample(0f, 3.3f, 9.8f, 124100)));
    }

    private MotionDetector calibratedDetector() {
        MotionDetector detector = new MotionDetector();
        detector.sample(0f, 0f, 9.8f, 0);
        detector.sample(0f, 0f, 9.8f, 1000);
        detector.sample(0f, 0f, 9.8f, 2600);
        return detector;
    }
}
