package ro.cloudinbuzunar.monitor;

final class MotionDetector {
    private static final long CALIBRATION_MILLIS = 2500;
    private static final long COOLDOWN_MILLIS = 120000;
    private static final float TRIGGER_DELTA = 2.2f;
    private static final int REQUIRED_SAMPLES = 2;

    private long calibrationStartedAt = -1;
    private long lastTriggeredAt = Long.MIN_VALUE;
    private float baselineX;
    private float baselineY;
    private float baselineZ;
    private int samples;
    private int movementSamples;

    float sample(float x, float y, float z, long nowMillis) {
        if (samples == 0) {
            baselineX = x;
            baselineY = y;
            baselineZ = z;
            calibrationStartedAt = nowMillis;
            samples = 1;
            return Float.NaN;
        }

        if (nowMillis - calibrationStartedAt < CALIBRATION_MILLIS) {
            updateBaseline(x, y, z, 0.12f);
            samples++;
            return Float.NaN;
        }

        float deltaX = x - baselineX;
        float deltaY = y - baselineY;
        float deltaZ = z - baselineZ;
        float delta = (float) Math.sqrt(
            deltaX * deltaX + deltaY * deltaY + deltaZ * deltaZ
        );

        if (
            lastTriggeredAt != Long.MIN_VALUE
            && nowMillis - lastTriggeredAt < COOLDOWN_MILLIS
        ) {
            movementSamples = 0;
            updateBaseline(x, y, z, 0.10f);
            return Float.NaN;
        }

        if (delta >= TRIGGER_DELTA) {
            movementSamples++;
        } else {
            movementSamples = 0;
            updateBaseline(x, y, z, 0.015f);
        }

        if (
            movementSamples >= REQUIRED_SAMPLES
        ) {
            lastTriggeredAt = nowMillis;
            movementSamples = 0;
            baselineX = x;
            baselineY = y;
            baselineZ = z;
            return Math.min(delta, 50f);
        }

        return Float.NaN;
    }

    private void updateBaseline(float x, float y, float z, float weight) {
        baselineX += (x - baselineX) * weight;
        baselineY += (y - baselineY) * weight;
        baselineZ += (z - baselineZ) * weight;
    }
}
