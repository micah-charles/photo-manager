import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.math.BigInteger;

public final class PairingV2Vector {
    private static byte[] field(String value) {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        return ByteBuffer.allocate(4 + bytes.length).putInt(bytes.length).put(bytes).array();
    }

    public static void main(String[] args) throws Exception {
        byte[] nonce = hex(args[2]);
        byte[] input = concat(field("photovault-pairing-v2"), field(args[0]), field(args[1]),
                ByteBuffer.allocate(4 + nonce.length).putInt(nonce.length).put(nonce).array());
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(input);
        System.out.printf("%032x %06d%n", new BigInteger(1, digest), new BigInteger(1, slice(digest, 0, 8)).mod(BigInteger.valueOf(1000000L)).longValue());
    }

    private static byte[] slice(byte[] source, int start, int length) { byte[] out = new byte[length]; System.arraycopy(source, start, out, 0, length); return out; }
    private static byte[] concat(byte[]... parts) { int size = 0; for (byte[] part : parts) size += part.length; byte[] out = new byte[size]; int offset = 0; for (byte[] part : parts) { System.arraycopy(part, 0, out, offset, part.length); offset += part.length; } return out; }
    private static byte[] hex(String value) { byte[] out = new byte[value.length() / 2]; for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(value.substring(i * 2, i * 2 + 2), 16); return out; }
}
