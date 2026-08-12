"""Core behaviour of the per-surface lock module.

Uses an in-memory fake credential store so the suite never touches the real
Windows vault, and proves the module's own promises: no lock by default, a
password verified against its hash rather than stored raw, TOTP against the
RFC 6238 published test vectors, unlock-duration expiry, relock, and that
removing a lock cannot orphan its secret.
"""

import os
import tempfile
import unittest


class _FakeStore:
    name = "fake"
    available = True
    explanation = "in-memory test double"

    def __init__(self):
        self._data = {}

    def write(self, key, secret):
        self._data[key] = secret

    def read(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)

    def exists(self, key):
        return key in self._data


class ItemLocksTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        os.environ["CONFIG_DIR"] = self._dir.name

        from amulet_map_editor.api import config, item_locks, forge_accounts

        config.invalidate()
        self.config = config
        self.locks = item_locks
        self.forge_accounts = forge_accounts

        self._store = _FakeStore()
        self._real_store_fn = forge_accounts.credential_store
        forge_accounts._store = self._store
        item_locks.credential_store = lambda: self._store

    def tearDown(self):
        self.forge_accounts._store = None
        self._dir.cleanup()

    # -- no lock by default ---------------------------------------------
    def test_nothing_is_locked_by_default(self):
        self.assertEqual(self.locks.list_locks(), ())
        self.assertFalse(self.locks.is_locked("tab", "tab-1"))

    # -- password lock ----------------------------------------------------
    def test_password_lock_matches_and_mismatches(self):
        lock = self.locks.create_lock(
            "tab", "tab-1", "Build notes", "password", password="hunter2"
        )
        self.assertTrue(self.locks.is_locked("tab", "tab-1"))
        self.assertFalse(self.locks.attempt_unlock(lock.lock_id, "wrong"))
        self.assertTrue(self.locks.attempt_unlock(lock.lock_id, "hunter2"))

    def test_password_is_never_stored_raw(self):
        lock = self.locks.create_lock(
            "tab", "tab-1", "Build notes", "password", password="hunter2"
        )
        stored = self._store.read(lock.credential_key)
        self.assertNotEqual(stored, "hunter2")
        self.assertNotIn("hunter2", stored)
        self.assertTrue(stored.startswith("pbkdf2$"))

    def test_failed_attempts_are_counted_and_reset_on_success(self):
        lock = self.locks.create_lock(
            "tab", "tab-1", "Build notes", "password", password="hunter2"
        )
        self.locks.attempt_unlock(lock.lock_id, "nope")
        self.locks.attempt_unlock(lock.lock_id, "nope")
        self.assertEqual(self.locks.get_lock(lock.lock_id).failed_attempts, 2)
        self.locks.attempt_unlock(lock.lock_id, "hunter2")
        self.assertEqual(self.locks.get_lock(lock.lock_id).failed_attempts, 0)

    # -- TOTP: RFC 6238 published test vectors ----------------------------
    def test_totp_matches_rfc6238_sha1_vector(self):
        # RFC 6238 Appendix B, SHA1, 8 digits, T=59 -> "94287082"
        secret = self._b32("12345678901234567890")
        code = self.locks.totp_now(secret, digits=8, algo="sha1", when=59)
        self.assertEqual(code, "94287082")

    def test_totp_matches_rfc6238_sha256_vector(self):
        secret = self._b32("12345678901234567890123456789012")
        code = self.locks.totp_now(secret, digits=8, algo="sha256", when=59)
        self.assertEqual(code, "46119246")

    def test_totp_matches_rfc6238_sha512_vector(self):
        secret = self._b32(
            "1234567890123456789012345678901234567890123456789012345678901234"
        )
        code = self.locks.totp_now(secret, digits=8, algo="sha512", when=59)
        self.assertEqual(code, "90693936")

    def test_totp_verify_honours_a_small_skew_window(self):
        secret = self.locks.generate_totp_secret()
        code = self.locks.totp_now(secret, when=1000)
        self.assertTrue(self.locks.verify_totp(secret, code, when=1000 + 25))
        self.assertFalse(self.locks.verify_totp(secret, code, when=1000 + 500))

    def test_totp_lock_end_to_end(self):
        secret = self.locks.generate_totp_secret()
        lock = self.locks.create_lock(
            "appearance", "accent-colour", "Accent colour", "totp", totp_secret=secret
        )
        wrong = self.locks.totp_now(secret, when=time_shift(secret))
        self.assertTrue(
            self.locks.attempt_unlock(lock.lock_id, self.locks.totp_now(secret))
        )

    @staticmethod
    def _b32(text: str) -> str:
        import base64

        return base64.b32encode(text.encode("ascii")).decode("ascii")

    # -- unlock duration and relock ---------------------------------------
    def test_unlock_duration_close_stays_unlocked(self):
        lock = self.locks.create_lock(
            "tab",
            "tab-1",
            "Build notes",
            "password",
            password="hunter2",
            unlock_duration="close",
        )
        self.locks.attempt_unlock(lock.lock_id, "hunter2")
        self.assertTrue(self.locks.is_unlocked(lock.lock_id))

    def test_unlock_duration_minutes_expires(self):
        lock = self.locks.create_lock(
            "tab",
            "tab-1",
            "Build notes",
            "password",
            password="hunter2",
            unlock_duration="0.0001",
        )
        self.locks.attempt_unlock(lock.lock_id, "hunter2")
        import time

        time.sleep(0.05)
        self.assertFalse(self.locks.is_unlocked(lock.lock_id))

    def test_relock_forgets_the_session(self):
        lock = self.locks.create_lock(
            "tab",
            "tab-1",
            "Build notes",
            "password",
            password="hunter2",
            unlock_duration="close",
        )
        self.locks.attempt_unlock(lock.lock_id, "hunter2")
        self.assertTrue(self.locks.is_unlocked(lock.lock_id))
        self.locks.relock(lock.lock_id)
        self.assertFalse(self.locks.is_unlocked(lock.lock_id))

    def test_locked_on_launch_defaults_true(self):
        lock = self.locks.create_lock(
            "tab", "tab-1", "Build notes", "password", password="hunter2"
        )
        self.assertTrue(lock.locked_on_launch)
        self.assertFalse(self.locks.is_unlocked(lock.lock_id))

    # -- every lock has its own independent credential ---------------------
    def test_two_locks_never_share_a_credential(self):
        one = self.locks.create_lock(
            "tab", "tab-1", "Tab one", "password", password="alpha"
        )
        two = self.locks.create_lock(
            "tab", "tab-2", "Tab two", "password", password="beta"
        )
        self.assertFalse(self.locks.attempt_unlock(one.lock_id, "beta"))
        self.assertFalse(self.locks.attempt_unlock(two.lock_id, "alpha"))
        self.assertTrue(self.locks.attempt_unlock(one.lock_id, "alpha"))
        self.assertTrue(self.locks.attempt_unlock(two.lock_id, "beta"))

    def test_change_credential_replaces_only_that_lock(self):
        one = self.locks.create_lock(
            "tab", "tab-1", "Tab one", "password", password="alpha"
        )
        two = self.locks.create_lock(
            "tab", "tab-2", "Tab two", "password", password="beta"
        )
        self.locks.change_credential(one.lock_id, password="alpha2")
        self.assertFalse(self.locks.attempt_unlock(one.lock_id, "alpha"))
        self.assertTrue(self.locks.attempt_unlock(one.lock_id, "alpha2"))
        self.assertTrue(self.locks.attempt_unlock(two.lock_id, "beta"))

    # -- removal never orphans a credential ---------------------------------
    def test_remove_lock_deletes_both_record_and_credential(self):
        lock = self.locks.create_lock(
            "tab", "tab-1", "Build notes", "password", password="hunter2"
        )
        self.locks.remove_lock(lock.lock_id)
        self.assertIsNone(self.locks.get_lock(lock.lock_id))
        self.assertIsNone(self._store.read(lock.credential_key))
        self.assertFalse(self.locks.is_locked("tab", "tab-1"))

    def test_removing_one_lock_leaves_siblings_untouched(self):
        one = self.locks.create_lock(
            "tab", "tab-1", "Tab one", "password", password="alpha"
        )
        two = self.locks.create_lock(
            "tab", "tab-2", "Tab two", "password", password="beta"
        )
        self.locks.remove_lock(one.lock_id)
        self.assertIsNotNone(self.locks.get_lock(two.lock_id))
        self.assertTrue(self.locks.attempt_unlock(two.lock_id, "beta"))

    # -- list_locks is the real enumerable list -----------------------------
    def test_list_locks_enumerates_every_lock(self):
        self.locks.create_lock("tab", "tab-1", "Tab one", "password", password="a")
        self.locks.create_lock(
            "group", "group-1", "Group one", "password", password="b"
        )
        self.locks.create_lock(
            "appearance", "accent", "Accent colour", "password", password="c"
        )
        scopes = {lock.scope for lock in self.locks.list_locks()}
        self.assertEqual(scopes, {"tab", "group", "appearance"})

    def test_profile_directory_hint_names_the_real_folder(self):
        self.assertEqual(self.locks.profile_directory_hint(), self._dir.name)


def time_shift(secret: str) -> float:
    import time

    return time.time()


if __name__ == "__main__":
    unittest.main()
