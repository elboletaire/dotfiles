"""Tests for research_queue.py: appending, the bound, and statuses that
follow the agents' states."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                ".."))
import research_queue as rq  # noqa: E402

NOW = 1_800_000_000


def agent(name, state):
    return {"host": "herdr", "name": name, "state": state}


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "arxiu", "queue.json")

    def add(self, mode="prefill", agent_name="orq", now=NOW, target="x"):
        return rq.append("person", target, f"investigar {target}", agent_name,
                         mode, path=self.path, now=now)

    def test_append_and_load(self):
        self.assertEqual(rq.load(self.path), [])
        e = self.add()
        self.assertEqual(e["status"], "prefilled")
        self.assertEqual(self.add(mode="send", agent_name="inv")["status"],
                         "sent")
        entries = rq.load(self.path)
        self.assertEqual([x["mode"] for x in entries], ["prefill", "send"])
        self.assertEqual(set(entries[0]), {"id", "at", "kind", "target",
                                           "label", "agent", "mode",
                                           "status"})
        self.assertNotEqual(entries[0]["id"], entries[1]["id"])

    def test_bounded(self):
        for i in range(rq.MAX_ENTRIES + 7):
            self.add(mode="send", agent_name="inv", now=NOW + i,
                     target=f"t{i}")
        entries = rq.load(self.path)
        self.assertEqual(len(entries), rq.MAX_ENTRIES)
        self.assertEqual(entries[0]["target"], "t7")
        self.assertEqual(entries[-1]["target"], f"t{rq.MAX_ENTRIES + 6}")

    def test_broken_file_is_empty(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            fh.write("{nope")
        self.assertEqual(rq.load(self.path), [])
        with open(self.path, "w") as fh:
            json.dump({"not": "a list"}, fh)
        self.assertEqual(rq.load(self.path), [])

    def test_default_path(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/c"}):
            os.environ.pop("ARXIU_QUEUE", None)
            self.assertEqual(rq.default_path(), "/c/arxiu/queue.json")
        with mock.patch.dict(os.environ, {"ARXIU_QUEUE": "/q.json"}):
            self.assertEqual(rq.default_path(), "/q.json")

    def test_a_new_prefill_discards_the_unsent_one(self):
        self.add(target="a")
        self.add(target="b", now=NOW + 1)
        self.assertEqual([e["status"] for e in rq.load(self.path)],
                         ["discarded", "prefilled"])

    def test_prefill_waits_for_enter_then_follows(self):
        self.add()
        steps = [("idle", "prefilled"), ("done", "prefilled"),
                 ("working", "working"), ("waiting", "waiting"),
                 ("working", "working"), ("idle", "done"),
                 ("working", "done")]
        for state, want in steps:
            entries = rq.update([agent("orq", state)], self.path, NOW + 5)
            self.assertEqual(entries[-1]["status"], want, state)

    def test_send_is_done_after_the_grace(self):
        self.add(mode="send", agent_name="inv")
        e = rq.update([agent("inv", "idle")], self.path, NOW + 5)[-1]
        self.assertEqual(e["status"], "sent")
        e = rq.update([agent("inv", "idle")], self.path,
                      NOW + rq.SEND_GRACE + 1)[-1]
        self.assertEqual(e["status"], "done")

    def test_agent_gone_is_stopped(self):
        self.add(mode="send", agent_name="inv")
        e = rq.update([agent("orq", "idle")], self.path, NOW + 1)[-1]
        self.assertEqual(e["status"], "stopped")

    def test_only_the_newest_follows_the_agent(self):
        self.add(mode="send", agent_name="inv", target="a")
        self.add(mode="send", agent_name="inv", target="b", now=NOW + 1)
        entries = rq.update([agent("inv", "working")], self.path, NOW + 2)
        self.assertEqual([e["status"] for e in entries], ["sent", "working"])
        entries = rq.update([agent("inv", "idle")], self.path, NOW + 3)
        self.assertEqual([e["status"] for e in entries], ["done", "done"])

    def test_update_saves_only_changes(self):
        self.add(mode="send", agent_name="inv")
        before = os.stat(self.path).st_mtime_ns
        rq.update([agent("inv", "idle")], self.path, NOW + 1)
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)


if __name__ == "__main__":
    unittest.main()
