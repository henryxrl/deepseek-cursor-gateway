from __future__ import annotations

from pathlib import Path
import stat
from tempfile import TemporaryDirectory
import threading
import unittest

from deepseek_cursor_gateway.reasoning_store import (
    ReasoningStore,
    conversation_scope,
    message_signature,
    tool_call_ids,
    tool_call_names,
    tool_call_signature,
    scoped_reasoning_keys,
    portable_reasoning_keys,
    turn_context_signature,
    compute_conversation_scopes,
    compute_turn_signatures,
    canonical_scope_message,
)


def _make_store(**kwargs) -> ReasoningStore:
    return ReasoningStore(":memory:", **kwargs)


class ReasoningStoreTests(unittest.TestCase):
    def test_file_store_creates_private_database_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            reasoning_content_path = (
                Path(temp_dir) / "nested" / "reasoning_content.sqlite3"
            )

            store = ReasoningStore(reasoning_content_path)
            store.close()

            self.assertTrue(reasoning_content_path.exists())
            self.assertEqual(stat.S_IMODE(reasoning_content_path.stat().st_mode), 0o600)

    def test_store_prunes_to_max_rows_and_can_clear(self) -> None:
        store = ReasoningStore(":memory:", max_rows=2)
        try:
            store.put("a", "reasoning a", {"role": "assistant"})
            store.put("b", "reasoning b", {"role": "assistant"})
            store.put("c", "reasoning c", {"role": "assistant"})

            self.assertIsNone(store.get("a"))
            self.assertEqual(store.get("b"), "reasoning b")
            self.assertEqual(store.get("c"), "reasoning c")
            self.assertEqual(store.clear(), 2)
            self.assertIsNone(store.get("b"))
            self.assertIsNone(store.get("c"))
        finally:
            store.close()

    def test_empty_reasoning_content_is_stored_as_present_value(self) -> None:
        store = ReasoningStore(":memory:")
        try:
            scope = conversation_scope([{"role": "user", "content": "lookup"}])
            tool_call = {
                "id": "call_empty",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{}"},
            }
            message = {
                "role": "assistant",
                "content": "",
                "reasoning_content": "",
                "tool_calls": [tool_call],
            }

            self.assertGreater(store.store_assistant_message(message, scope), 0)
            self.assertEqual(store.get(f"scope:{scope}:tool_call:call_empty"), "")
            self.assertEqual(
                store.lookup_for_message(
                    {"role": "assistant", "content": "", "tool_calls": [tool_call]},
                    scope,
                ),
                "",
            )
        finally:
            store.close()

    def test_put_and_get_roundtrip(self) -> None:
        store = _make_store()
        try:
            store.put("k1", "deep thought", {"role": "assistant", "content": "hi"})
            self.assertEqual(store.get("k1"), "deep thought")
        finally:
            store.close()

    def test_get_nonexistent_key_returns_none(self) -> None:
        store = _make_store()
        try:
            self.assertIsNone(store.get("no_such_key"))
        finally:
            store.close()

    def test_put_overwrites_existing_key(self) -> None:
        store = _make_store()
        try:
            store.put("k1", "first", {"role": "assistant"})
            store.put("k1", "second", {"role": "assistant"})
            self.assertEqual(store.get("k1"), "second")
        finally:
            store.close()

    def test_put_non_string_reasoning_is_ignored(self) -> None:
        store = _make_store()
        try:
            store.put("k1", 12345, {"role": "assistant"})  # type: ignore[arg-type]
            self.assertIsNone(store.get("k1"))
        finally:
            store.close()

    def test_put_empty_string_reasoning_is_stored(self) -> None:
        store = _make_store()
        try:
            store.put("k1", "", {"role": "assistant"})
            self.assertEqual(store.get("k1"), "")
        finally:
            store.close()

    def test_clear_empty_store_returns_zero(self) -> None:
        store = _make_store()
        try:
            self.assertEqual(store.clear(), 0)
        finally:
            store.close()

    def test_concurrent_puts_do_not_corrupt(self) -> None:
        store = _make_store(max_rows=5000)
        n_threads = 10
        n_puts_per = 100

        def _put(offset: int) -> None:
            for i in range(n_puts_per):
                store.put(f"t{offset}_{i}", f"r{offset}_{i}", {"role": "assistant"})

        threads = [threading.Thread(target=_put, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for t in range(n_threads):
            for i in range(n_puts_per):
                val = store.get(f"t{t}_{i}")
                self.assertIsNotNone(val)
                self.assertEqual(val, f"r{t}_{i}")
        store.close()

    def test_prune_by_age_removes_expired_rows(self) -> None:
        store = _make_store(max_age_seconds=3600 * 24)
        try:
            # Write a row with a very old timestamp by manipulating directly
            store._conn.execute(
                "INSERT INTO reasoning_cache(key, reasoning, message_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                ("old", "old reasoning", "{}", 100.0),  # year 1970
            )
            store._conn.commit()
            store.put("fresh", "new reasoning", {"role": "assistant"})
            store.prune()
            self.assertIsNone(store.get("old"))
            self.assertEqual(store.get("fresh"), "new reasoning")
        finally:
            store.close()

    def test_prune_by_age_keeps_fresh_rows(self) -> None:
        store = _make_store(max_age_seconds=3600)
        try:
            store.put("fresh", "still valid", {"role": "assistant"})
            store.prune()
            self.assertEqual(store.get("fresh"), "still valid")
        finally:
            store.close()

    def test_prune_by_rows_keeps_newest(self) -> None:
        store = _make_store(max_rows=3)
        try:
            store.put("a", "r1", {"role": "assistant"})
            store.put("b", "r2", {"role": "assistant"})
            store.put("c", "r3", {"role": "assistant"})
            store.put("d", "r4", {"role": "assistant"})
            self.assertIsNone(store.get("a"))
            self.assertIsNotNone(store.get("b"))
            self.assertIsNotNone(store.get("c"))
            self.assertIsNotNone(store.get("d"))
        finally:
            store.close()

    def test_prune_zero_limit_noops(self) -> None:
        store = _make_store(max_rows=0, max_age_seconds=0)
        try:
            store.put("k", "v", {"role": "assistant"})
            deleted = store.prune()
            self.assertEqual(deleted, 0)
            self.assertEqual(store.get("k"), "v")
        finally:
            store.close()

    def test_store_assistant_message_non_assistant_returns_zero(self) -> None:
        store = _make_store()
        try:
            scope = conversation_scope([])
            result = store.store_assistant_message(
                {"role": "user", "content": "hi"}, scope
            )
            self.assertEqual(result, 0)
        finally:
            store.close()

    def test_store_assistant_message_no_reasoning_returns_zero(self) -> None:
        store = _make_store()
        try:
            scope = conversation_scope([])
            result = store.store_assistant_message(
                {"role": "assistant", "content": "hi"}, scope
            )
            self.assertEqual(result, 0)
        finally:
            store.close()

    def test_lookup_for_message_finds_stored_reasoning(self) -> None:
        store = _make_store()
        try:
            tool_call = {
                "id": "call_abc",
                "type": "function",
                "function": {"name": "search", "arguments": "{}"},
            }
            message = {
                "role": "assistant",
                "content": "",
                "reasoning_content": "secret reasoning",
                "tool_calls": [tool_call],
            }
            scope = conversation_scope([{"role": "user", "content": "find"}])
            store.store_assistant_message(message, scope)

            lookup_msg = {
                "role": "assistant",
                "content": "",
                "tool_calls": [tool_call],
            }
            self.assertEqual(
                store.lookup_for_message(lookup_msg, scope), "secret reasoning"
            )
        finally:
            store.close()

    def test_lookup_for_message_with_portable_keys(self) -> None:
        store = _make_store()
        try:
            prior = [{"role": "user", "content": "hello"}]
            scope = conversation_scope(prior)
            tool_call = {
                "id": "call_p",
                "type": "function",
                "function": {"name": "port", "arguments": "{}"},
            }
            message = {
                "role": "assistant",
                "content": "",
                "reasoning_content": "portable reasoning",
                "tool_calls": [tool_call],
            }
            store.store_assistant_message(
                message, scope, cache_namespace="ns1", prior_messages=prior
            )

            lookup_msg = {"role": "assistant", "content": "", "tool_calls": [tool_call]}
            self.assertEqual(
                store.lookup_for_message(
                    lookup_msg, scope, cache_namespace="ns1", prior_messages=prior
                ),
                "portable reasoning",
            )
        finally:
            store.close()

    def test_lookup_for_message_miss_returns_none(self) -> None:
        store = _make_store()
        try:
            self.assertIsNone(
                store.lookup_for_message({"role": "assistant"}, "noscope")
            )
        finally:
            store.close()

    def test_backfill_portable_aliases(self) -> None:
        store = _make_store()
        try:
            prior = [{"role": "user", "content": "count"}]
            tool_call = {
                "id": "call_b",
                "type": "function",
                "function": {"name": "tally", "arguments": "{}"},
            }
            message = {"role": "assistant", "tool_calls": [tool_call]}
            n = store.backfill_portable_aliases(message, "backfilled", "ns2", prior)
            self.assertGreater(n, 0)

            # Now look it up via portable keys
            found = store.lookup_for_message(
                message, "irrelevant_scope", cache_namespace="ns2", prior_messages=prior
            )
            self.assertEqual(found, "backfilled")
        finally:
            store.close()

    def test_backfill_portable_aliases_non_string_reasoning_returns_zero(self) -> None:
        store = _make_store()
        try:
            n = store.backfill_portable_aliases(
                {"role": "assistant"}, 12345, "ns", [{"role": "user", "content": "x"}]
            )
            self.assertEqual(n, 0)
        finally:
            store.close()

    def test_backfill_portable_aliases_no_namespace_returns_zero(self) -> None:
        store = _make_store()
        try:
            n = store.backfill_portable_aliases(
                {"role": "assistant"},
                "reasoning",
                "",
                [{"role": "user", "content": "x"}],
            )
            self.assertEqual(n, 0)
        finally:
            store.close()

    def test_close_can_be_called_multiple_times(self) -> None:
        store = _make_store()
        store.close()
        # Second close should not raise (silently ignored by RLock + closed conn)
        store.close()

    def test_in_memory_store_uses_colon_memory(self) -> None:
        store = ReasoningStore(":memory:")
        self.assertEqual(store.reasoning_content_path, ":memory:")
        store.close()

    def test_prune_noop_when_no_limits(self) -> None:
        store = _make_store()
        try:
            store.put("k", "v", {"role": "assistant"})
            self.assertEqual(store.prune(), 0)
            self.assertEqual(store.get("k"), "v")
        finally:
            store.close()

    # --- Pure function tests (signature / key helpers) ---

    def test_tool_call_ids_returns_all_ids(self) -> None:
        msg = {
            "tool_calls": [
                {"id": "a", "function": {"name": "f1", "arguments": "{}"}},
                {"id": "b", "function": {"name": "f2", "arguments": "{}"}},
            ]
        }
        self.assertEqual(tool_call_ids(msg), ["a", "b"])

    def test_tool_call_ids_ignores_missing_id(self) -> None:
        msg = {"tool_calls": [{"type": "function", "function": {"name": "x"}}]}
        self.assertEqual(tool_call_ids(msg), [])

    def test_tool_call_names_returns_non_empty_names(self) -> None:
        msg = {
            "tool_calls": [
                {"function": {"name": "alpha"}},
                {"function": {"name": "beta"}},
                {"function": {}},
            ]
        }
        self.assertEqual(tool_call_names(msg), ["alpha", "beta"])

    def test_tool_call_signature_is_deterministic(self) -> None:
        tc = {
            "id": "x",
            "type": "function",
            "function": {"name": "f", "arguments": '{"a":1}'},
        }
        self.assertEqual(tool_call_signature(tc), tool_call_signature(tc))

    def test_tool_call_signature_differs_on_arguments(self) -> None:
        tc1 = {"id": "x", "function": {"name": "f", "arguments": '{"a":1}'}}
        tc2 = {"id": "x", "function": {"name": "f", "arguments": '{"a":2}'}}
        self.assertNotEqual(tool_call_signature(tc1), tool_call_signature(tc2))

    def test_message_signature_is_deterministic(self) -> None:
        msg = {"role": "assistant", "content": "hello"}
        self.assertEqual(message_signature(msg), message_signature(msg))

    def test_message_signature_includes_tool_call_id(self) -> None:
        msg1 = {
            "role": "assistant",
            "tool_calls": [{"id": "a", "function": {"name": "f", "arguments": "{}"}}],
        }
        msg2 = {
            "role": "assistant",
            "tool_calls": [{"id": "b", "function": {"name": "f", "arguments": "{}"}}],
        }
        self.assertNotEqual(message_signature(msg1), message_signature(msg2))

    def test_scoped_reasoning_keys_includes_tool_name_fallback(self) -> None:
        tool_call = {"id": "c1", "function": {"name": "search", "arguments": "{}"}}
        msg = {"role": "assistant", "content": "", "tool_calls": [tool_call]}
        scope = "myscope"
        keys = scoped_reasoning_keys(msg, scope)
        self.assertIn(f"scope:{scope}:tool_name:search", keys)

    def test_portable_reasoning_keys_empty_without_namespace(self) -> None:
        prior = [{"role": "user", "content": "x"}]
        keys = portable_reasoning_keys({"role": "assistant"}, "", prior)
        self.assertEqual(keys, [])

    def test_portable_reasoning_keys_with_namespace(self) -> None:
        prior = [{"role": "user", "content": "hi"}]
        msg = {"role": "assistant", "content": "ok"}
        keys = portable_reasoning_keys(msg, "myns", prior)
        self.assertTrue(all(k.startswith("namespace:myns:turn:") for k in keys))

    def test_turn_context_signature_starts_at_last_user(self) -> None:
        prior = [
            {"role": "system", "content": "be helpful"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ]
        sig = turn_context_signature(prior)
        self.assertIsInstance(sig, str)
        self.assertGreater(len(sig), 0)

    def test_turn_context_signature_empty_returns_valid_hash(self) -> None:
        sig = turn_context_signature([])
        self.assertIsInstance(sig, str)
        self.assertEqual(len(sig), 64)  # SHA-256 hex

    def test_compute_conversation_scopes_length(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        scopes = compute_conversation_scopes(msgs)
        self.assertEqual(len(scopes), 3)  # empty + 2 messages

    def test_compute_conversation_scopes_with_namespace(self) -> None:
        msgs = [{"role": "user", "content": "x"}]
        scopes = compute_conversation_scopes(msgs, namespace="n1")
        self.assertEqual(len(scopes), 2)

    def test_compute_turn_signatures_length(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        sigs = compute_turn_signatures(msgs)
        self.assertEqual(len(sigs), 4)  # 0-prefix + 3 message positions

    def test_compute_turn_signatures_consecutive_users(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        sigs = compute_turn_signatures(msgs)
        self.assertEqual(len(sigs), 3)

    def test_canonical_scope_message_preserves_known_keys(self) -> None:
        msg = {
            "role": "assistant",
            "content": "hi",
            "name": "test",
            "tool_call_id": "ct1",
            "prefix": True,
            "extra": "should_be_dropped",
        }
        canonical = canonical_scope_message(msg)
        self.assertIn("role", canonical)
        self.assertIn("content", canonical)
        self.assertIn("name", canonical)
        self.assertIn("tool_call_id", canonical)
        self.assertIn("prefix", canonical)
        self.assertNotIn("extra", canonical)

    def test_conversation_scope_deterministic(self) -> None:
        msgs = [{"role": "user", "content": "test"}]
        self.assertEqual(
            conversation_scope(msgs),
            conversation_scope(msgs),
        )


if __name__ == "__main__":
    unittest.main()
