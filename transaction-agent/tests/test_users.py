from transaction_agent import users


def test_verify_correct_passphrase(tmp_path):
    path = str(tmp_path / "users.sqlite")
    users.create_user("krish", "hunter2", path=path)
    assert users.verify("krish", "hunter2", path=path) is True


def test_verify_rejects_wrong_passphrase(tmp_path):
    path = str(tmp_path / "users.sqlite")
    users.create_user("krish", "hunter2", path=path)
    assert users.verify("krish", "WRONG", path=path) is False


def test_verify_rejects_unknown_user(tmp_path):
    path = str(tmp_path / "users.sqlite")
    users.create_user("krish", "hunter2", path=path)
    assert users.verify("ghost", "hunter2", path=path) is False


def test_verify_rejects_empty_credentials(tmp_path):
    path = str(tmp_path / "users.sqlite")
    users.create_user("krish", "hunter2", path=path)
    assert users.verify("", "", path=path) is False
    assert users.verify("krish", "", path=path) is False


def test_passphrases_are_salted_per_user(tmp_path):
    path = str(tmp_path / "users.sqlite")
    users.create_user("alice", "samepassword", path=path)
    users.create_user("bob", "samepassword", path=path)
    import sqlite3

    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT username, salt, passphrase_hash FROM users").fetchall()
    conn.close()
    salts = {r[1] for r in rows}
    hashes = {r[2] for r in rows}
    assert len(salts) == 2, "each user should get a distinct random salt"
    assert len(hashes) == 2, "identical passphrases must not produce identical hashes"


def test_user_exists(tmp_path):
    path = str(tmp_path / "users.sqlite")
    assert users.user_exists("krish", path=path) is False
    users.create_user("krish", "hunter2", path=path)
    assert users.user_exists("krish", path=path) is True
