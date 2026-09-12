package ro.cloudinbuzunar.monitor;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import org.junit.Test;

public final class ApiClientTest {
    @Test
    public void rejectsHttpOnTheHttpsPortWithAClearMessage() {
        IllegalArgumentException error = assertThrows(
            IllegalArgumentException.class,
            () -> ApiClient.normalizeServerUrl("http://192.168.1.225:8443")
        );

        assertEquals(
            "Portul 8443 folosește HTTPS. Scrie https:// la începutul adresei.",
            error.getMessage()
        );
    }

    @Test
    public void acceptsTheConfiguredHttpsAddress() {
        assertEquals(
            "https://192.168.1.225:8443",
            ApiClient.normalizeServerUrl("https://192.168.1.225:8443/")
        );
    }
}
