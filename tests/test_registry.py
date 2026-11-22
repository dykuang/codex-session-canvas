import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from project_registry import (RegistryError, empty_registry, validate_registry, path_key,
                              project_for_folder, graph_edges, load_registry, save_registry)
from project_bridge import project_data


def sample():
    return {"version": 1, "projects": [
        {"id": "A", "name": "Project A", "folders": ["C:/Research/A"]},
        {"id": "B", "name": "Project B", "folders": ["C:/Research/B"]},
        {"id": "C", "name": "Project C", "folders": ["D:/C", "E:/Cases/C"]}],
        "relationships": [{"from": "A", "to": "C", "type": "successor"},
                           {"from": "B", "to": "C", "type": "successor"}]}


class RegistryTests(unittest.TestCase):
    def test_dag_merge_and_multifolder(self):
        cfg = validate_registry(sample())
        self.assertEqual(2, len(graph_edges(cfg)))
        self.assertEqual('logical:C', project_for_folder(r'e:\cases\c\session', cfg))
        self.assertEqual('logical:C', project_for_folder('D:/C/nested', cfg))
        self.assertEqual('logical:A', project_for_folder('C:/Research/A', cfg))
        self.assertIsNone(project_for_folder('C:/Research/Apple', cfg))

    def test_longest_match(self):
        cfg = sample()
        cfg['projects'][2]['folders'].append('C:/Research/A/sub')
        cfg = validate_registry(cfg)
        self.assertEqual('logical:C', project_for_folder('C:/Research/A/sub/leaf', cfg))

    def test_cycle_duplicate_self_and_invalid_nodes(self):
        for new_edge in [
            {"from": "C", "to": "A", "type": "successor"},
            {"from": "C", "to": "C", "type": "successor"},
            {"from": "A", "to": "C", "type": "successor"},
            {"from": "Z", "to": "C", "type": "successor"},
        ]:
            cfg = sample()
            cfg['relationships'].append(new_edge)
            with self.subTest(new_edge=new_edge), self.assertRaises(RegistryError):
                validate_registry(cfg)

    def test_same_folder_different_case_windows(self):
        cfg = sample()
        cfg['projects'][1]['folders'].append('c:\\research\\a')
        with self.assertRaises(RegistryError):
            validate_registry(cfg)
        self.assertNotEqual(path_key('/Work/Alpha'), path_key('/work/Alpha'))

    def test_file_save_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / 'projects.json'
            self.assertEqual(empty_registry(), load_registry(filename))
            save_registry(filename, sample())
            self.assertEqual(3, len(load_registry(filename)['projects']))
            new_cfg = sample()
            new_cfg['projects'][2]['name'] = 'Updated'
            save_registry(filename, new_cfg)
            self.assertTrue(filename.with_suffix('.json.bak').exists())
            invalid = sample()
            invalid['relationships'].append({"from": "C", "to": "A", "type": "successor"})
            with self.assertRaises(RegistryError):
                save_registry(filename, invalid)
            self.assertEqual('Updated', load_registry(filename)['projects'][2]['name'])

    def test_invalid_config_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / 'projects.json'
            filename.write_text('{bad json')
            with self.assertRaises(RegistryError):
                save_registry(filename, sample())
            self.assertEqual('{bad json', filename.read_text())

    def test_bridge_fallback_and_session_dedup(self):
        cfg = sample()
        sessions = [{"id": 'one', "cwd": 'D:/C/s', "project": 'D:/C', "name": '1'},
                    {"id": 'two', "cwd": 'E:/Cases/C/test', "project": 'E:/Cases/C', "name": '2'},
                    {"id": 'three', "cwd": 'C:/Research/A', "project": 'C:/Research/A', "name": '3'},
                    {"id": 'four', "cwd": 'C:/Unmapped', "project": 'C:/Unmapped', "name": '4'}]
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / 'projects.json'
            save_registry(filename, cfg)
            original = {"sessions": sessions, "projects": [], "focus": 'all'}
            mapped = project_data(original, filename, focus='D:/C')
            self.assertEqual('logical:C', mapped['focus'])
            self.assertEqual(2, next(p['count'] for p in mapped['projects'] if p['id'] == 'logical:C'))
            self.assertTrue(any(p['id'] == 'C:/Unmapped' for p in mapped['projects']))
            self.assertEqual(2, len(mapped['projectGraph']))
            self.assertEqual('D:/C', mapped['sessions'][0]['sourceProject'])


if __name__ == '__main__':
    unittest.main()