"""Run standalone teaching examples only. Never reads a real ESA database."""
from pathlib import Path
import json, sys, unittest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
class RecordingResult(unittest.TextTestResult):
    def startTest(self,test):
        if not hasattr(self,'names'): self.names=[]
        self.names.append(test.id())
        super().startTest(test)
suite=unittest.defaultTestLoader.discover(str(HERE),pattern='test_labs.py')
result=unittest.TextTestRunner(verbosity=2,resultclass=RecordingResult).run(suite)
report={'scope':'STANDALONE_TEACHING_ONLY_NOT_PRODUCT_ACCEPTANCE','tests_run':result.testsRun,'success':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'test_names':getattr(result,'names',[]),'python':sys.version.split()[0],'student_mastery':'NOT_ASSESSED'}
(HERE/'last_run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
raise SystemExit(0 if result.wasSuccessful() else 1)
