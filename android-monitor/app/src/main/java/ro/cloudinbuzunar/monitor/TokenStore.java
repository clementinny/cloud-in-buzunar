package ro.cloudinbuzunar.monitor;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class TokenStore {
    private static final String KEY_ALIAS = "cloud_monitor_device_token";
    private static final String PREFS = "cloud_monitor_secure";
    private static final String TOKEN = "token";
    private static final String IV = "iv";

    private TokenStore() {}

    static void save(Context context, String token) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());

        byte[] encrypted = cipher.doFinal(
            token.getBytes(StandardCharsets.UTF_8)
        );
        SharedPreferences preferences = context.getSharedPreferences(
            PREFS,
            Context.MODE_PRIVATE
        );
        preferences.edit()
            .putString(TOKEN, Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .putString(IV, Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .apply();
    }

    static String read(Context context) {
        try {
            SharedPreferences preferences = context.getSharedPreferences(
                PREFS,
                Context.MODE_PRIVATE
            );
            String encryptedValue = preferences.getString(TOKEN, null);
            String ivValue = preferences.getString(IV, null);

            if (encryptedValue == null || ivValue == null) {
                return null;
            }

            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            GCMParameterSpec parameterSpec = new GCMParameterSpec(
                128,
                Base64.decode(ivValue, Base64.NO_WRAP)
            );
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), parameterSpec);
            byte[] decrypted = cipher.doFinal(
                Base64.decode(encryptedValue, Base64.NO_WRAP)
            );
            return new String(decrypted, StandardCharsets.UTF_8);
        } catch (Exception error) {
            clear(context);
            return null;
        }
    }

    static void clear(Context context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .clear()
            .apply();
    }

    private static SecretKey getOrCreateKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        keyStore.load(null);

        if (keyStore.containsAlias(KEY_ALIAS)) {
            return ((KeyStore.SecretKeyEntry) keyStore.getEntry(
                KEY_ALIAS,
                null
            )).getSecretKey();
        }

        KeyGenerator keyGenerator = KeyGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_AES,
            "AndroidKeyStore"
        );
        keyGenerator.init(
            new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT
                    | KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build()
        );
        return keyGenerator.generateKey();
    }
}
