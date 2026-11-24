"""v0.6 snapshot contract, legacy coexistence and privacy regression fixtures."""
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from chatgpt_metadata import SCHEMA, SnapshotError, load_snapshot, validate_snapshot
from chatgpt_bridge import merge_chatgpt
from project_registry import save_registry, load_registry, RegistryError


def fixture(*, pages=None, age=0):
    stamp=(datetime.now(timezone.utc)-timedelta(days=age)).isoformat()
    return {"schema":SCHEMA,"version":1,"scope":"user-provided-metadata",
            "exportedAt":stamp,
            "pages": pages or [{"page":1,"complete":True,"projects":[],
                                "conversations":[],"relationships":[]}]}


class ChatGPTMetadataTests(unittest.TestCase):
    def test_pages_archives_dedup_rename_and_explicit_provenance(self):
        raw=fixture(pages=[
            {"page":1,"complete":True,"projects":[{"id":"P","title":"Old"}],
             "conversations":[{"id":"a","title":"First","projectId":"P","archived":False},
                              {"id":"b","title":"Same title","projectId":"P"}],
             "relationships":[{"from":"a","to":"b","type":"reference","evidence":"user-confirmed"}]},
            {"page":2,"complete":True,"projects":[{"id":"P","title":"AI-Skills/Agents"}],
             "conversations":[{"id":"a","title":"Renamed","projectId":"P","archived":True},
                              {"id":"c","title":"Same title","projectId":"P","archived":False}],
             "relationships":[{"from":"b","to":"c","type":"handoff","evidence":"source-verified"}]}
        ])
        cleaned=validate_snapshot(raw)
        self.assertEqual("complete",cleaned["status"])
        self.assertEqual(2,cleaned["pageCount"])
        self.assertEqual("AI-Skills/Agents",cleaned["projectRecords"][0]["title"])
        self.assertEqual(3,len(cleaned["conversationRecords"]))
        a=next(c for c in cleaned["conversationRecords"] if c["id"]=="a")
        b=next(c for c in cleaned["conversationRecords"] if c["id"]=="b")
        self.assertEqual("Renamed",a["title"])
        self.assertTrue(a["archived"])
        self.assertIsNone(b["archived"])
        self.assertEqual(2,len(cleaned["relationships"]))
        self.assertEqual("chatgpt:b",cleaned["relationships"][0]["to"])
        self.assertEqual("source-verified",cleaned["relationships"][1]["evidence"])

    def test_incomplete_stale_and_invalid_reports(self):
        partial=fixture(pages=[{"page":1,"complete":False,"projects":[],"conversations":[]}])
        self.assertEqual("incomplete",validate_snapshot(partial)["status"])
        self.assertEqual("stale",validate_snapshot(fixture(age=45))["status"])
        partial["pages"][0]["page"]=2
        with self.assertRaises(SnapshotError):
            validate_snapshot(partial)
        raw=fixture()
        raw["pages"][0]["conversations"]=[{"id":"c","title":"x","messages":[{"role":"user","content":"SECRET"}]}]
        with self.assertRaises(SnapshotError):
            validate_snapshot(raw)
        raw["pages"][0]["conversations"]=[{"id":"c","title":"x","archived":"false"}]
        with self.assertRaises(SnapshotError):
            validate_snapshot(raw)
        with tempfile.TemporaryDirectory() as folder:
            snap=Path(folder)/"snapshot.json"
            self.assertEqual("unavailable",load_snapshot(snap)["status"])
            snap.write_text(json.dumps(raw),encoding="utf-8")
            self.assertEqual("invalid",load_snapshot(snap)["status"])
            self.assertNotIn("SECRET",repr(load_snapshot(snap)))

    def test_relationship_missing_nodes_is_not_fabricated(self):
        raw=fixture(pages=[{"page":1,"complete":True,"projects":[],
            "conversations":[{"id":"a","title":"A"}],
            "relationships":[{"from":"a","to":"missing","type":"parent","evidence":"source-verified"}]}])
        parsed=validate_snapshot(raw)
        self.assertFalse(parsed["relationships"])
        self.assertTrue(parsed["warnings"])

    def test_project_mirror_id_and_collision_preserve_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"projects.json"
            save_registry(path,{"version":1,"projects":[
                {"id":"P","name":"Old Local Project","folders":["C:/Research/镜像"],
                 "chatgptProjectId":"mirror-123"},
                {"id":"Q","name":"Same Name","folders":["D:/Elsewhere"]}],
                "relationships":[{"from":"P","to":"Q","type":"successor"}]})
            snap=Path(folder)/"metadata.json"
            uuid="123e4567-e89b-42d3-a456-426614174000"
            raw=fixture(pages=[{"page":1,"complete":True,
                "projects":[{"id":"mirror-123","title":"AI-Skills/Agents"},{"id":"other","title":"Same Name"}],
                "conversations":[{"id":uuid,"title":"Two sources same ID","projectId":"mirror-123"},
                                 {"id":"second","title":"Two sources same ID","projectId":"other"}],
                "relationships":[]}])
            snap.write_text(json.dumps(raw),encoding="utf-8")
            local={"id":uuid,"name":"Codex local","project":"logical:P",
                   "cwd":"C:\\Research\\镜像","archived":False,"updatedUnix":1}
            base={"sessions":[local],"projects":[{"id":"logical:P","name":"Old Local Project","count":1,
                "folders":["C:/Research/镜像"],"configured":True},
                {"id":"logical:Q","name":"Same Name","count":0,"configured":True}],
                "focus":"logical:P","projectGraph":[{"from":"logical:P","to":"logical:Q","type":"successor"}]}
            result=merge_chatgpt(base,path,snap)
            sessions=result["sessions"]
            self.assertEqual(3,len(sessions))
            self.assertEqual(len({x["id"] for x in sessions}),3)
            self.assertIn(uuid,{x["id"] for x in sessions})
            self.assertIn("chatgpt:"+uuid,{x["id"] for x in sessions})
            self.assertEqual("logical:P",next(x for x in sessions if x["source"]=="chatgpt" and x["id"].endswith(uuid))["project"])
            self.assertEqual("AI-Skills/Agents",next(p for p in result["projects"] if p["id"]=="logical:P")["name"])
            self.assertEqual("Same Name",next(p for p in result["projects"] if p["id"]=="chatgpt:other")["name"])
            self.assertEqual("Same Name",next(p for p in result["projects"] if p["id"]=="logical:Q")["name"])
            self.assertEqual("Codex local",next(s for s in sessions if s["id"]==uuid)["name"])
            self.assertEqual("logical:P",result["focus"])
            self.assertEqual(1,len(result["projectGraph"]))
            self.assertEqual("mirror-123",load_registry(path)["projects"][0]["chatgptProjectId"])
            self.assertEqual(raw,json.loads(snap.read_text(encoding="utf-8")))

    def test_unknown_membership_no_title_based_guess(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/"legacy.json"
            save_registry(config,{"version":1,"projects":[{"id":"A","name":"Same","folders":[]}],"relationships":[]})
            snap=Path(folder)/"cloud.json"
            raw=fixture(pages=[{"page":1,"complete":True,
                "projects":[{"id":"id-1","title":"Same"}],
                "conversations":[{"id":"chat-1","title":"Same","projectId":"id-1"},
                                 {"id":"chat-2","title":"Unknown project","projectId":"deleted"}],
                "relationships":[]}])
            snap.write_text(json.dumps(raw),encoding="utf-8")
            result=merge_chatgpt({"sessions":[],"projects":[{"id":"logical:A","name":"Same","count":0}]},config,snap)
            self.assertEqual("chatgpt:id-1",next(s for s in result["sessions"] if s["id"]=="chatgpt:chat-1")["project"])
            self.assertEqual("chatgpt:unassigned",next(s for s in result["sessions"] if s["id"]=="chatgpt:chat-2")["project"])
            self.assertTrue(result["chatgptSource"]["warnings"])

    def test_mirror_duplicates_rejected_and_old_registry_unchanged(self):
        old={"version":1,"projects":[{"id":"P","name":"Legacy","folders":["D:/Work"]}],"relationships":[]}
        self.assertNotIn("chatgptProjectId",load_registry_from_dict(old)["projects"][0])
        dup=deepcopy(old)
        dup["projects"][0]["chatgptProjectId"]="id"
        dup["projects"].append({"id":"Q","name":"Second","folders":["E:/Work"],"chatgptProjectId":"id"})
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RegistryError):
                save_registry(Path(folder)/"projects.json",dup)


def load_registry_from_dict(raw):
    from project_registry import validate_registry
    return validate_registry(raw)


if __name__ == "__main__":
    unittest.main()
