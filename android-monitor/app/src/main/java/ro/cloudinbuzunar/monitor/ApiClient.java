package ro.cloudinbuzunar.monitor;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class ApiClient {
    static final String SERVER_URL = "http://127.0.0.1:8080";

    private final String token;

    ApiClient(String token) {
        this.token = token;
    }

    static String pair(String code, String deviceName) throws Exception {
        JSONObject payload = new JSONObject()
            .put("code", code)
            .put("device_name", deviceName);
        JSONObject response = request(
            "POST",
            "/api/monitor/devices/pair",
            payload,
            null
        );
        return response.getString("token");
    }

    JSONObject arm(String sourceId, String cameraFacing) throws Exception {
        return authenticatedRequest(
            "POST",
            "/api/monitor/source/arm",
            new JSONObject()
                .put("source_id", sourceId)
                .put("camera_facing", cameraFacing)
        );
    }

    JSONObject poll(
        String sourceId,
        String actualState,
        String errorMessage
    ) throws Exception {
        JSONObject payload = new JSONObject()
            .put("source_id", sourceId)
            .put("actual_state", actualState);

        if (errorMessage != null) {
            payload.put("error", errorMessage);
        }

        return authenticatedRequest(
            "POST",
            "/api/monitor/source/poll",
            payload
        );
    }

    void disarm(String sourceId) throws Exception {
        authenticatedRequest(
            "DELETE",
            "/api/monitor/source/" + sourceId,
            null
        );
    }

    void sendOffer(
        String sessionId,
        String type,
        String sdp
    ) throws Exception {
        authenticatedRequest(
            "POST",
            "/api/monitor/offer",
            new JSONObject()
                .put("session_id", sessionId)
                .put(
                    "offer",
                    new JSONObject()
                        .put("type", type)
                        .put("sdp", sdp)
                )
        );
    }

    JSONObject getAnswer(String sessionId) throws Exception {
        return authenticatedRequest(
            "GET",
            "/api/monitor/answer?session_id=" + sessionId,
            null
        );
    }

    boolean heartbeat(String sessionId) throws Exception {
        JSONObject response = authenticatedRequest(
            "POST",
            "/api/monitor/heartbeat",
            new JSONObject().put("session_id", sessionId)
        );
        return response.optBoolean("active", false);
    }

    void stopSession(String sessionId) throws Exception {
        authenticatedRequest(
            "DELETE",
            "/api/monitor/session/" + sessionId,
            null
        );
    }

    private JSONObject authenticatedRequest(
        String method,
        String path,
        JSONObject body
    ) throws Exception {
        return request(method, path, body, token);
    }

    private static JSONObject request(
        String method,
        String path,
        JSONObject body,
        String token
    ) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(
            SERVER_URL + path
        ).openConnection();
        connection.setRequestMethod(method);
        connection.setConnectTimeout(5000);
        connection.setReadTimeout(10000);
        connection.setRequestProperty("Accept", "application/json");

        if (token != null) {
            connection.setRequestProperty(
                "Authorization",
                "Bearer " + token
            );
        }

        if (body != null) {
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            connection.setDoOutput(true);
            connection.setRequestProperty(
                "Content-Type",
                "application/json; charset=utf-8"
            );
            connection.setFixedLengthStreamingMode(bytes.length);

            try (OutputStream output = connection.getOutputStream()) {
                output.write(bytes);
            }
        }

        int status = connection.getResponseCode();
        InputStream stream = status >= 400
            ? connection.getErrorStream()
            : connection.getInputStream();
        String responseText = readStream(stream);
        connection.disconnect();

        JSONObject response = responseText.isEmpty()
            ? new JSONObject()
            : new JSONObject(responseText);

        if (status < 200 || status >= 300) {
            throw new ApiException(
                status,
                response.optString(
                    "error",
                    "Server error: HTTP " + status
                )
            );
        }

        return response;
    }

    private static String readStream(InputStream stream) throws Exception {
        if (stream == null) {
            return "";
        }

        StringBuilder result = new StringBuilder();

        try (
            BufferedReader reader = new BufferedReader(
                new InputStreamReader(stream, StandardCharsets.UTF_8)
            )
        ) {
            String line;

            while ((line = reader.readLine()) != null) {
                result.append(line);
            }
        }

        return result.toString();
    }

    static final class ApiException extends Exception {
        final int status;

        ApiException(int status, String message) {
            super(message);
            this.status = status;
        }
    }
}
