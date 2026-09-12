package ro.cloudinbuzunar.monitor;

import org.json.JSONObject;
import org.json.JSONArray;

import java.io.BufferedReader;
import java.io.DataOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class ApiClient {
    static final String DEFAULT_SERVER_URL = "http://127.0.0.1:8080";

    private final String token;
    private final String serverUrl;

    ApiClient(String token) {
        this(token, DEFAULT_SERVER_URL);
    }

    ApiClient(String token, String serverUrl) {
        this.token = token;
        this.serverUrl = normalizeServerUrl(serverUrl);
    }

    static String pair(
        String serverUrl,
        String code,
        String deviceName
    ) throws Exception {
        JSONObject payload = new JSONObject()
            .put("code", code)
            .put("device_name", deviceName);
        JSONObject response = request(
            normalizeServerUrl(serverUrl),
            "POST",
            "/api/monitor/devices/pair",
            payload,
            null
        );
        return response.getString("token");
    }

    JSONObject health() throws Exception {
        return request(serverUrl, "GET", "/api/health", null, null);
    }

    JSONObject alertFeed(int limit) throws Exception {
        return authenticatedRequest(
            "GET",
            "/api/system/alerts/feed?limit=" + limit,
            null
        );
    }

    void acknowledgeAlerts(JSONArray eventIds) throws Exception {
        authenticatedRequest(
            "POST",
            "/api/system/alerts/feed/ack",
            new JSONObject().put("event_ids", eventIds)
        );
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
        String errorMessage,
        String recordingMode
    ) throws Exception {
        JSONObject payload = new JSONObject()
            .put("source_id", sourceId)
            .put("actual_state", actualState)
            .put("recording_mode", recordingMode);

        if (errorMessage != null) {
            payload.put("error", errorMessage);
        }

        return authenticatedRequest(
            "POST",
            "/api/monitor/source/poll",
            payload
        );
    }

    void uploadRecording(
        File file,
        String mode,
        String cameraFacing,
        long startedAt,
        long endedAt
    ) throws Exception {
        String boundary = "CloudMonitor-" + System.nanoTime();
        HttpURLConnection connection = (HttpURLConnection) new URL(
            serverUrl + "/api/monitor/recordings"
        ).openConnection();
        connection.setRequestMethod("POST");
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(120000);
        connection.setDoOutput(true);
        connection.setChunkedStreamingMode(256 * 1024);
        connection.setRequestProperty("Accept", "application/json");
        connection.setRequestProperty("Authorization", "Bearer " + token);
        connection.setRequestProperty(
            "Content-Type",
            "multipart/form-data; boundary=" + boundary
        );

        try (DataOutputStream output = new DataOutputStream(
            connection.getOutputStream()
        )) {
            writeFormField(output, boundary, "mode", mode);
            writeFormField(
                output,
                boundary,
                "camera_facing",
                cameraFacing == null ? "" : cameraFacing
            );
            writeFormField(
                output,
                boundary,
                "started_at_ms",
                Long.toString(startedAt)
            );
            writeFormField(
                output,
                boundary,
                "ended_at_ms",
                Long.toString(endedAt)
            );
            output.writeBytes("--" + boundary + "\r\n");
            output.writeBytes(
                "Content-Disposition: form-data; name=\"recording\"; "
                    + "filename=\"segment"
                    + ("audio".equals(mode) ? ".m4a" : ".mp4")
                    + "\"\r\n"
            );
            output.writeBytes(
                "Content-Type: "
                    + ("audio".equals(mode) ? "audio/mp4" : "video/mp4")
                    + "\r\n\r\n"
            );

            try (FileInputStream input = new FileInputStream(file)) {
                byte[] buffer = new byte[256 * 1024];
                int count;

                while ((count = input.read(buffer)) >= 0) {
                    output.write(buffer, 0, count);
                }
            }

            output.writeBytes("\r\n--" + boundary + "--\r\n");
        }

        int status = connection.getResponseCode();
        InputStream stream = status >= 400
            ? connection.getErrorStream()
            : connection.getInputStream();
        String responseText = readStream(stream);
        connection.disconnect();

        if (status < 200 || status >= 300) {
            JSONObject response = responseText.isEmpty()
                ? new JSONObject()
                : new JSONObject(responseText);
            throw new ApiException(
                status,
                response.optString("error", "Upload failed: HTTP " + status)
            );
        }
    }

    private static void writeFormField(
        DataOutputStream output,
        String boundary,
        String name,
        String value
    ) throws Exception {
        output.writeBytes("--" + boundary + "\r\n");
        output.writeBytes(
            "Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n"
        );
        output.write(value.getBytes(StandardCharsets.UTF_8));
        output.writeBytes("\r\n");
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
        return request(serverUrl, method, path, body, token);
    }

    private static JSONObject request(
        String serverUrl,
        String method,
        String path,
        JSONObject body,
        String token
    ) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(
            serverUrl + path
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

    static String normalizeServerUrl(String value) {
        String normalized = value == null ? "" : value.trim();

        while (normalized.endsWith("/")) {
            normalized = normalized.substring(0, normalized.length() - 1);
        }

        if (
            !normalized.startsWith("https://")
            && !normalized.startsWith("http://")
        ) {
            throw new IllegalArgumentException(
                "Adresa serverului trebuie să înceapă cu https:// sau http://"
            );
        }

        return normalized;
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
