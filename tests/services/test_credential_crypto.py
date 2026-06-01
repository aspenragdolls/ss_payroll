from app.services.credential_crypto import decrypt_credential, encrypt_credential


def test_encrypt_decrypt_roundtrip():
    plain = "abcd-efgh-ijkl-mnop"
    encrypted = encrypt_credential(plain)
    assert encrypted != plain
    assert decrypt_credential(encrypted) == plain
