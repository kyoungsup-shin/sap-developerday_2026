"""Evaluation configuration, immutable runs, result polling and safe traces."""
import json
import os
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch
from django.test import SimpleTestCase
from gateway import harness_evaluation as evaluation
from gateway.errors import HarnessError
from scripts.evaluate_scenarios import sanitize_event, apply_evaluation_rules, score_scenario


class EvaluationTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {'DEMO_EVALUATION_DIR':self.directory.name, 'DEMO_HARNESS_STATE_DIR':self.directory.name+'/settings'})
        environment.start(); self.addCleanup(environment.stop)

    def test_validation_and_configured_assertions(self):
        config = evaluation.evaluation_defaults()
        self.assertEqual(len(config['scenarios']), 5)
        for value in (None, {}, {**config,'timeout_seconds':0}, {**config,'minimum_score':float('nan')}, {**config,'scenarios':[config['scenarios'][0],config['scenarios'][0]]}):
            with self.subTest(value=value), self.assertRaises(HarnessError): evaluation.validate_evaluation(value)
        result = score_scenario('custom','Custom request','Review',[])
        config['minimum_score'] = 0
        case = config['scenarios'][0]
        apply_evaluation_rules(result, case, config)
        self.assertFalse(result['passed'], 'A zero threshold must not allow missing Chat/RPT/termination.')
        self.assertAlmostEqual(sum(item['weight'] for checks in result['categories'].values() for item in checks),100)

    def test_trace_redaction_preserves_defect_evidence_without_secrets(self):
        with patch.dict(os.environ, {'AICORE_CLIENT_SECRET':'private-client-secret'}):
            event = sanitize_event({'type':'error','data':{'access_token':'private-token','message':'Bearer another-token private-client-secret'},'at':0})
        self.assertTrue(event['redacted_secrets'])
        self.assertNotIn('another-token', json.dumps(event)); self.assertNotIn('private-client-secret', json.dumps(event)); self.assertNotIn('private-token', json.dumps(event))
        self.assertIn('REDACTED', json.dumps(event))

    def test_failed_start_retains_safe_status(self):
        with patch('gateway.harness_evaluation.subprocess.Popen', side_effect=OSError('secret-client-detail')):
            with self.assertRaises(HarnessError): evaluation.start_evaluation({})
        runs = evaluation.evaluation_runs()
        self.assertEqual(runs[0]['state'], 'failed')
        self.assertNotIn('secret-client-detail', json.dumps(runs))
        self.assertNotIn('process_id', json.dumps(runs))

    def test_started_run_pins_revision_and_reports_completion(self):
        gate = threading.Event(); finished = threading.Event(); captured = []
        class Process:
            pid = 123456
            def __init__(self, command, **kwargs):
                captured.append(command)
                self.directory = Path(command[command.index('--output-dir')+1])
            def poll(self): return None if not gate.is_set() else 0
            def wait(self, timeout=None):
                gate.wait(5)
                (self.directory/'five_scenario_report.json').write_text(json.dumps({'scenarios':[{'id':'strawberry_order'}],'overall_score':100}))
                finished.set(); return 0
        with patch('gateway.harness_evaluation.subprocess.Popen', Process):
            run = evaluation.start_evaluation({'scenario_ids':['strawberry_order']})
            try:
                self.assertEqual(run['revision'],0)
                self.assertEqual(evaluation.evaluation_result(run['id'])['state'],'running')
                self.assertNotIn('process_id', run)
                command = captured[0]
                self.assertEqual(command[command.index('--settings-revision')+1],'0')
                with self.assertRaises(HarnessError): evaluation.start_evaluation({})
            finally: gate.set()
            finished.wait(5)
        # Join the monitor via the service lock, without an arbitrary wait.
        import time
        deadline = time.monotonic()+5
        while run['id'] in evaluation._active and time.monotonic()<deadline: threading.Event().wait(.01)
        result = evaluation.evaluation_result(run['id'])
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['report']['overall_score'],100)

    def test_interrupted_run_keeps_partial_report_and_rejects_paths(self):
        identity = 'a'*32; directory = evaluation._job_directory(identity); directory.mkdir()
        evaluation._write_status(directory, {'id':identity,'state':'running','revision':0,'started_at':0,'scenario_count':5})
        (directory/'five_scenario_report.json').write_text(json.dumps({'scenarios':[{'id':'partial'}],'running':True}))
        result = evaluation.evaluation_result(identity)
        self.assertEqual(result['state'],'interrupted'); self.assertEqual(len(result['report']['scenarios']),1)
        with self.assertRaises(HarnessError): evaluation.evaluation_result('../../.env')
        self.assertEqual(self.client.get('/api/harness/evaluations/'+identity).status_code,200)
