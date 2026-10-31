import unittest
from request_projection import Request, Facts, project
from rrf_demo import fuse
from sqlite_store import DemoStore, Conflict
from history import History
from dates_preview import interval, overlaps, Preview, preview_state
from evidence_view import Source, model_view, ui_view, citations_exist

class RequestTests(unittest.TestCase):
    def test_knowledge_without_loan_fields(self):
        self.assertEqual(project(Request(knowledge=True), Facts(("date",)))["turn_actions"], ["retry_knowledge"])
    def test_preview_requires_fields(self):
        self.assertEqual(project(Request(preview=True), Facts(("date",)))["turn_actions"], ["input"])
    def test_mixed_can_offer_two_independent_actions(self):
        self.assertEqual(project(Request(True, True), Facts(("date",)))["turn_actions"], ["retry_knowledge", "input"])
    def test_busy_and_complete(self):
        self.assertEqual(project(Request(True, True), Facts(busy=True))["turn_actions"], ["running"])
        self.assertEqual(project(Request(False, True), Facts(knowledge_ready=True))["turn_actions"], ["complete"])

class RankingTests(unittest.TestCase):
    def test_order(self):
        self.assertEqual([x[0] for x in fuse(["a","b","c"],["b","c","d"])], ["b","c","a","d"])
    def test_score(self):
        self.assertAlmostEqual(dict(fuse(["a","b"],["b"]))["b"], 1/62 + 1/61)
    def test_one_retriever_and_empty(self):
        self.assertEqual(fuse([], []), [])
        self.assertEqual(fuse(["a"], []), [("a", 1/61)])
    def test_deterministic_tie(self):
        self.assertEqual([x[0] for x in fuse(["z"],["a"])], ["a","z"])

class StoreTests(unittest.TestCase):
    def setUp(self): self.s = DemoStore()
    def tearDown(self): self.s.close()
    def test_revision_conflict_preserves_first_update(self):
        self.assertEqual(self.s.edit("first",1),2)
        with self.assertRaises(Conflict): self.s.edit("stale",1)
        self.assertEqual(self.s.db.execute("SELECT revision,value FROM task").fetchone(), (2,"first"))
    def test_duplicate_command(self):
        self.assertEqual(self.s.submit("c",{"x":1}), self.s.submit("c",{"x":1}))
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM ticket").fetchone()[0],1)
    def test_command_mismatch_is_not_a_new_ticket(self):
        self.s.submit("c",{"x":1})
        with self.assertRaises(Conflict): self.s.submit("c",{"x":2})
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM ticket").fetchone()[0],1)
    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.s.db:
                self.s.db.execute("UPDATE task SET value='partial'")
                raise RuntimeError("fail before commit")
        self.assertEqual(self.s.db.execute("SELECT value FROM task").fetchone()[0],"initial")

class HistoryTests(unittest.TestCase):
    def setUp(self): self.h = History()
    def tearDown(self): self.h.close()
    def test_old_detail_not_in_recent_is_still_available(self):
        self.assertNotIn(1, [x[0] for x in self.h.page(limit=50)])
        self.assertEqual(self.h.detail(1), (1,"answer 1"))
    def test_pagination_reads_all_without_duplicates(self):
        seen=[];cursor=None
        while rows := self.h.page(before=cursor):
            seen.extend(x[0] for x in rows);cursor=rows[-1][0]
        self.assertEqual(seen, list(range(55,0,-1)))
    def test_search_and_missing(self):
        self.assertIn((1,"answer 1"), self.h.page(search="answer 1"))
        self.assertEqual(self.h.page(search="no-match"), [])
        self.assertIsNone(self.h.detail(99))
    def test_insert_between_pages_does_not_repeat_prior_page(self):
        first=self.h.page(limit=20)
        self.h.db.execute("INSERT INTO answer VALUES(56,'new')");self.h.db.commit()
        second=self.h.page(before=first[-1][0],limit=20)
        self.assertEqual(len(set(x[0] for x in first+second)),40)
        self.assertEqual(second[0][0],35)

class DateTests(unittest.TestCase):
    def test_adjacent_intervals(self):
        self.assertFalse(overlaps(interval("2026-11-01","2026-11-03"), interval("2026-11-04","2026-11-05")))
    def test_same_day_and_overlap(self):
        self.assertTrue(overlaps(interval("2026-11-01","2026-11-03"), interval("2026-11-03","2026-11-03")))
    def test_preview_exact_deadline(self):
        p=Preview(600,2)
        self.assertEqual(preview_state(p,now=599,current_revision=2),"current")
        self.assertEqual(preview_state(p,now=600,current_revision=2),"expired")
    def test_revision_stale_and_invalid_dates(self):
        self.assertEqual(preview_state(Preview(600,2),now=1,current_revision=3),"stale")
        with self.assertRaises(ValueError): interval("2026-11-04","2026-11-03")

class EvidenceTests(unittest.TestCase):
    def setUp(self): self.s=[Source("loan","Loan","v1","Only loan context","sec 1")]
    def test_ui_preserves_location_and_version(self):
        self.assertEqual(ui_view(self.s)["loan"]["locator"],"sec 1")
        self.assertEqual(ui_view(self.s)["loan"]["version"],"v1")
    def test_model_is_a_distinct_projection(self):
        self.assertEqual(set(model_view(self.s)[0]),{"id","title","content"})
        self.assertNotIn("locator",model_view(self.s)[0])
    def test_unknown_and_empty_reference(self):
        self.assertFalse(citations_exist(["repair"],self.s))
        self.assertFalse(citations_exist([],self.s))
    def test_existence_does_not_validate_claim_text(self):
        wrong_text="This proves a repair is complete"
        self.assertTrue(citations_exist(["loan"],self.s))
        self.assertNotIn(wrong_text,self.s[0].text)
        # This demonstrates the limitation; it is not a semantic validator.
