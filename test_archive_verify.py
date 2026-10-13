import json
from pathlib import Path
import tempfile
import unittest

import archive_verify as av


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "project"
        (self.src / "docs").mkdir(parents=True)
        (self.src / "docs" / "notes.txt").write_text("hello\n" * 100)
        (self.src / "main.py").write_text("print('hi')\n")
        (self.src / ".venv" / "lib").mkdir(parents=True)
        (self.src / ".venv" / "lib" / "big.bin").write_bytes(b"x" * 5000)
        self.vault = self.root / "vault"

    def tearDown(self):
        self.tmp.cleanup()

    def test_plan_finds_rebuildable(self):
        rows = av.rebuildable(self.root)
        self.assertEqual([r["path"] for r in rows], ["project/.venv"])
        self.assertEqual(rows[0]["bytes"], 5000)

    def test_pack_proves_and_skips_rebuildable(self):
        out = av.pack(self.src, self.vault)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["files"], 2)
        self.assertEqual(out["rebuildable_not_packed"], 1)
        self.assertTrue(self.src.exists(), "pack must never delete the original")
        proof = json.loads((self.vault / "project.proof.json").read_text())
        self.assertIn("docs/notes.txt", proof["sha256"])
        self.assertTrue(av.verify(self.vault / "project.zip")["ok"])

    def test_pack_refuses_to_overwrite(self):
        av.pack(self.src, self.vault)
        self.assertFalse(av.pack(self.src, self.vault)["ok"])

    def test_verify_catches_a_mismatch(self):
        av.pack(self.src, self.vault)
        proof_file = self.vault / "project.proof.json"
        proof = json.loads(proof_file.read_text())
        proof["sha256"]["main.py"] = "0" * 64
        proof_file.write_text(json.dumps(proof))
        out = av.verify(self.vault / "project.zip")
        self.assertFalse(out["ok"])
        self.assertEqual(out["mismatched"], ["main.py"])

    def test_unpack_round_trip_and_refuses_non_empty(self):
        av.pack(self.src, self.vault)
        dest = self.root / "restored"
        self.assertTrue(av.unpack(self.vault / "project.zip", dest)["ok"])
        self.assertEqual((dest / "main.py").read_text(), "print('hi')\n")
        self.assertFalse(av.unpack(self.vault / "project.zip", dest)["ok"])


if __name__ == "__main__":
    unittest.main()
