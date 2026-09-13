package com.photovault.companion;

import android.content.Context;
import android.content.SharedPreferences;

import com.southernstorm.noise.protocol.HandshakeState;

import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.InvalidAlgorithmParameterException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.Base64;
import java.util.UUID;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import javax.crypto.Mac;

/**
 * Noise XX responder for the Companion pairing endpoint.
 *
 * The private Noise static key is encrypted with an Android Keystore AES key;
 * it is never written as plaintext SharedPreferences data.  This class only
 * handles the handshake.  The caller must still require explicit user
 * confirmation on both peers before promoting the session to trusted.
 */
final class NoisePairingResponder {
    static final String PROTOCOL = "photovault-pairing-v1";
    private static final String KEY_ALIAS = "PhotoVault.Pairing.Storage.v1";
    private static final String PREFS = "photovault_pairing_identity";
    private static final String VALUE = "noise_static_private";

    private final HandshakeState handshake;
    private final String expectedRemoteFingerprint;
    private boolean firstMessage = true;
    private boolean complete;
    private boolean localConfirmed;
    private boolean desktopConfirmed;
    private final long expiresAt = System.currentTimeMillis() + 120000L;

    private NoisePairingResponder(byte[] privateKey, String expectedRemoteFingerprint) throws Exception {
        this.expectedRemoteFingerprint = expectedRemoteFingerprint;
        handshake = new HandshakeState("Noise_XX_25519_ChaChaPoly_SHA256", HandshakeState.RESPONDER);
        handshake.getLocalKeyPair().setPrivateKey(privateKey, 0);
        byte[] prologue = PROTOCOL.getBytes(StandardCharsets.UTF_8);
        handshake.setPrologue(prologue, 0, prologue.length);
        handshake.start();
    }

    static NoisePairingResponder create(Context context) throws Exception { return create(context, null); }
    static NoisePairingResponder create(Context context, String expectedRemoteFingerprint) throws Exception {
        return new NoisePairingResponder(loadOrCreateStaticKey(context), expectedRemoteFingerprint);
    }

    byte[] receive(byte[] message) throws Exception {
        ensureLive();
        byte[] payload = new byte[1024];
        handshake.readMessage(message, 0, message.length, payload, 0);
        if (firstMessage) {
            firstMessage = false;
            byte[] response = new byte[65535];
            int length = handshake.writeMessage(response, 0, new byte[0], 0, 0);
            return Arrays.copyOf(response, length);
        }
        complete = true;
        return new byte[0];
    }

    boolean isComplete() { return complete; }
    boolean isExpired() { return System.currentTimeMillis() >= expiresAt; }
    void confirmLocal() throws Exception { ensureLive(); if (complete) localConfirmed = true; }
    void confirmDesktop() throws Exception { ensureLive(); if (complete) desktopConfirmed = true; }
    boolean isPaired() { return complete && localConfirmed && desktopConfirmed; }
    boolean isTrustedRemote() throws Exception { return complete && (expectedRemoteFingerprint == null || expectedRemoteFingerprint.equals(remoteFingerprint())); }
    byte[] handshakeHash() { return handshake.getHandshakeHash(); }
    String sas() throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(handshakeHash());
        long value = new BigInteger(1, digest).mod(BigInteger.valueOf(1000000L)).longValue();
        String digits = String.format(java.util.Locale.ROOT, "%06d", value);
        return digits.substring(0, 3) + " " + digits.substring(3);
    }
    String publicKeyFingerprint() throws Exception {
        byte[] publicKey = new byte[handshake.getLocalKeyPair().getPublicKeyLength()];
        handshake.getLocalKeyPair().getPublicKey(publicKey, 0);
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(publicKey);
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < 8; i++) result.append(String.format(java.util.Locale.ROOT, "%02x", digest[i]));
        return result.toString();
    }
    String remoteFingerprint() throws Exception {
        byte[] publicKey = new byte[handshake.getRemotePublicKey().getPublicKeyLength()];
        handshake.getRemotePublicKey().getPublicKey(publicKey, 0);
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(publicKey);
        StringBuilder result = new StringBuilder();
        for (int i = 0; i < 8; i++) result.append(String.format(java.util.Locale.ROOT, "%02x", digest[i]));
        return result.toString();
    }

    String transferSessionToken() throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(handshakeHash(), "HmacSHA256"));
        byte[] digest = mac.doFinal("PhotoVault transfer session v1".getBytes(StandardCharsets.UTF_8));
        return Base64.getUrlEncoder().withoutPadding().encodeToString(digest);
    }

    private void ensureLive() throws Exception {
        if (System.currentTimeMillis() >= expiresAt) throw new Exception("pairing session expired");
    }

    static String newSessionId() { return "pair_" + UUID.randomUUID().toString().replace("-", ""); }

    private static byte[] loadOrCreateStaticKey(Context context) throws Exception {
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        String encoded = prefs.getString(VALUE, null);
        SecretKey storageKey = storageKey();
        if (encoded != null) {
            byte[] packed = Base64.getDecoder().decode(encoded);
            byte[] iv = Arrays.copyOf(packed, 12);
            byte[] ciphertext = Arrays.copyOfRange(packed, 12, packed.length);
            try {
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, storageKey, new GCMParameterSpec(128, iv));
                return cipher.doFinal(ciphertext);
            } catch (InvalidAlgorithmParameterException incompatibleKey) {
                // A development build may have created the key with the default
                // randomized-IV policy. Recreate only this unusable pairing key.
                context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().remove(VALUE).apply();
                KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore"); keyStore.load(null);
                keyStore.deleteEntry(KEY_ALIAS);
                return loadOrCreateStaticKey(context);
            }
        }
        byte[] privateKey = new byte[32]; new SecureRandom().nextBytes(privateKey);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        // Android Keystore must generate the encryption IV itself. Supplying
        // an IV here triggers "Caller-provided IV not permitted".
        cipher.init(Cipher.ENCRYPT_MODE, storageKey);
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(privateKey);
        byte[] packed = new byte[iv.length + ciphertext.length];
        System.arraycopy(iv, 0, packed, 0, iv.length); System.arraycopy(ciphertext, 0, packed, iv.length, ciphertext.length);
        prefs.edit().putString(VALUE, Base64.getEncoder().encodeToString(packed)).apply();
        return privateKey;
    }

    private static SecretKey storageKey() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(KEY_ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance("AES", "AndroidKeyStore");
            generator.init(new android.security.keystore.KeyGenParameterSpec.Builder(KEY_ALIAS, android.security.keystore.KeyProperties.PURPOSE_ENCRYPT | android.security.keystore.KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(android.security.keystore.KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(android.security.keystore.KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(false).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) store.getEntry(KEY_ALIAS, null)).getSecretKey();
    }
}
