import com.southernstorm.noise.protocol.HandshakeState;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Tiny test-only responder used to prove the vendored Java library interops. */
public final class NoiseHandshakeResponder {
    public static void main(String[] args) throws Exception {
        byte[] prologue = "photovault-pairing-v1".getBytes("UTF-8");
        HandshakeState state = new HandshakeState("Noise_XX_25519_ChaChaPoly_SHA256", HandshakeState.RESPONDER);
        state.getLocalKeyPair().generateKeyPair();
        state.setPrologue(prologue, 0, prologue.length);
        state.start();
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, "UTF-8"));
        byte[] first = Base64.getDecoder().decode(input.readLine());
        byte[] payload = new byte[1024];
        state.readMessage(first, 0, first.length, payload, 0);
        byte[] second = new byte[65535];
        int secondLength = state.writeMessage(second, 0, new byte[0], 0, 0);
        System.out.println(Base64.getEncoder().encodeToString(java.util.Arrays.copyOf(second, secondLength)));
        System.out.flush();
        byte[] third = Base64.getDecoder().decode(input.readLine());
        state.readMessage(third, 0, third.length, payload, 0);
        byte[] hash = state.getHandshakeHash();
        System.out.println(Base64.getEncoder().encodeToString(hash));
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(hash, "HmacSHA256"));
        byte[] token = mac.doFinal("PhotoVault transfer session v1".getBytes("UTF-8"));
        System.out.println(Base64.getUrlEncoder().withoutPadding().encodeToString(token));
    }
}
