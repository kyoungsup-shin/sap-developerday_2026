"""Saved configuration must change runtime consumers, not just manifest labels."""
import asyncio
import json
import os
import tempfile
from copy import deepcopy
from unittest.mock import patch

from django.test import SimpleTestCase
from gateway.harness_settings import read_revision, settings_scope
from gateway.harness_configuration import configuration_manifest, update_configuration, context_limits
from gateway.harness_profile import get_profile, runtime_timeout
from gateway.local_tools import execute_authorized_tool, tool_ids_for_subagent
from gateway.tool_catalog import native_tool_schema
from gateway.prompt_resources import get_prompt
from gateway.joule_cli import _settings as joule_settings
from gateway.rpt_decision import _request as rpt_request
from gateway.errors import HarnessError
from gateway import agent_network as network
from gateway import human_review
from gateway.tests.test_tool_contract import sop, rpt, card_for, payload, HTTPA2ATests
from gateway.a2a_transport import send_task, handoff_envelope, discover_cards, validate_card


class ManagementTests(SimpleTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {'DEMO_HARNESS_STATE_DIR': self.directory.name})
        environment.start(); self.addCleanup(environment.stop)

    def section(self, name):
        return configuration_manifest()['sections'][name]

    def save(self, name, value):
        return update_configuration({'section': name, 'value': value, 'expected_revision': read_revision()['revision']})

    def test_tools_descriptions_permissions_and_data_change_real_calculation(self):
        original = read_revision()
        config = self.section('tools')
        config['contracts'][0]['description'] = 'Locate registered context evidence first.'
        for row in config['specialist_permissions']:
            if row['name'] == 'Procurement Specialist': row['tools'] = ['search_business_context']
        self.save('tools', config)
        self.assertEqual(native_tool_schema('search_business_context')['function']['description'].strip(), config['contracts'][0]['description'])
        self.assertEqual(tool_ids_for_subagent('Procurement Specialist'), ('search_business_context',))
        with self.assertRaises(ValueError):
            execute_authorized_tool('Procurement Specialist', 'retrieve_business_evidence', {'context_id':'CTX-RM-STRAWBERRY'})
        datasets = self.section('data')
        datasets['product_cost_assumption.csv'][0]['SELLING_PRICE'] = '9.00'
        self.save('data', datasets)
        changed = execute_authorized_tool('Profitability and Cost Specialist', 'calculate_profitability_scenarios', {'context_id':'CTX-PROD-LEMON'})['result']
        self.assertNotEqual(changed['scenarios'][0]['quarter_profit'], 101856)
        with settings_scope(original):
            before = execute_authorized_tool('Profitability and Cost Specialist', 'calculate_profitability_scenarios', {'context_id':'CTX-PROD-LEMON'})['result']
            self.assertEqual(before['scenarios'][0]['quarter_profit'], 101856)

    def test_runtime_grounding_rpt_and_joule_consumers(self):
        runtime = self.section('runtime')
        runtime['max_handoffs'] = 1; runtime['max_tool_turns'] = 2
        runtime['timeouts']['a2a_connect'] = 4.5
        runtime['context_limits']['history_characters'] = 5
        self.save('runtime', runtime)
        self.assertEqual(get_profile()['runtime']['max_handoffs'], 1)
        self.assertEqual(runtime_timeout('a2a_connect'), 4.5)
        self.assertEqual(network._history_digest([{'role':'user','content':'123456789'}])[0]['content'], '12345')
        grounding = self.section('grounding'); grounding['repository_id'] = 'saved-repository'
        grounding['prompts']['sop_system_en'] = 'Use verified SOP sources only.'
        self.save('grounding', grounding)
        from gateway.grounding import public_grounding_config
        with patch('gateway.grounding._settings', return_value={}):
            self.assertEqual(public_grounding_config()['repository_id'], 'saved-repository')
        self.assertEqual(get_prompt('grounding.sop_system_en'), 'Use verified SOP sources only.')
        decision = self.section('rpt'); decision['decision']['risk']['instructions'] = 'Assess documented operational risk.'
        self.save('rpt', decision)
        self.assertIn('Assess documented operational risk.', json.dumps(rpt_request('Documented state')))
        self.save('joule', {'solution_id':'solution-demo','asset_name':'existing-work-agent'})
        with patch('gateway.joule_cli._load_repo_env'):
            self.assertEqual(joule_settings()[1:3], ('solution-demo', 'existing-work-agent'))

    def test_rpt_state_repairs_source_language_before_emitting_decision(self):
        from gateway.rpt_decision import _grounded_state
        with patch('gateway.rpt_decision.chat_text', side_effect=['설비팀 review. SOP-01.', 'Facilities Team review. SOP-01.']) as model:
            state = _grounded_state('Review the kit', 'Verified SOP-01')
        self.assertEqual(state, 'Facilities Team review. SOP-01.')
        self.assertEqual(model.call_count, 2)
        self.assertIn('Preserve all facts', model.call_args.args[0][0]['content'])
        with patch('gateway.rpt_decision.chat_text', return_value='설비팀 review.'), self.assertRaises(RuntimeError):
            _grounded_state('Review the kit', 'Verified SOP-01')

    def test_invalid_settings_do_not_save(self):
        variants = []
        agents = self.section('agents'); agents['teams'][0]['sub_agents'] = ['Missing Specialist']; variants.append(('agents', agents))
        tools = self.section('tools'); tools['contracts'][0]['inputs'][0]['name'] = 'wrong'; variants.append(('tools', tools))
        data = self.section('data'); data['operations_evidence.csv'][0]['CONTEXT_ID'] = 'UNKNOWN'; variants.append(('data', data))
        data = self.section('data'); data['product_cost_assumption.csv'][0]['BASE_FX_USD_EUR'] = 'NaN'; variants.append(('data', data))
        grounding = self.section('grounding'); grounding['sop_required'] = False; variants.append(('grounding', grounding))
        grounding = self.section('grounding'); grounding['prompts']['user'] = 'Missing placeholders'; variants.append(('grounding', grounding))
        runtime = self.section('runtime'); runtime['context_limits']['max_specialists'] = 0; variants.append(('runtime', runtime))
        decision = self.section('rpt'); decision['prompts']['grounded_state_user'] = '{unknown}'; variants.append(('rpt', decision))
        variants.append(('joule', {'solution_id':'only','asset_name':''}))
        evaluation = self.section('evaluation'); evaluation['weights']['chat_quality'] = 19; variants.append(('evaluation', evaluation))
        for name, value in variants:
            with self.subTest(section=name), self.assertRaises(HarnessError): self.save(name, value)
            self.assertEqual(read_revision()['revision'], 0)

    def test_manifest_and_preview_api_preserve_contract_and_do_not_expose_paths(self):
        response = self.client.get('/api/harness/configuration')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.directory.name, response.content.decode())
        self.assertNotIn('client_secret', response.content.decode())
        data = self.section('data')['business_context.csv']
        import csv, io
        output = io.StringIO(); writer = csv.DictWriter(output, fieldnames=list(data[0])); writer.writeheader(); writer.writerows(data)
        request = {'filename':'business_context.csv','csv':output.getvalue()}
        result = self.client.post('/api/harness/data/preview', json.dumps(request), content_type='application/json')
        self.assertEqual(result.status_code, 200); self.assertFalse(result.json()['saved'])
        self.assertEqual(read_revision()['revision'], 0)
        request['csv'] = 'CONTEXT_ID,CONTEXT_ID\na,b'
        self.assertEqual(self.client.post('/api/harness/data/preview', json.dumps(request), content_type='application/json').status_code, 422)

    def test_human_input_checkpoint_and_reassessment_keep_revision_and_evidence(self):
        runtime = self.section('runtime'); runtime['hitl_mode'] = 'require_input'; self.save('runtime', runtime)
        choices = [('search_grounding', {'query':'Review SOP','reason':'Required'}), ('finish_review', {'summary':'Evidence reviewed. Await requested input. SOP-01.','reason':'Review ready'})]
        prior = [{'team_id':'fb-procurement-team','finding':'Quotation documented','read_only':True}]
        with patch.object(network, 'discover_cards', return_value={}), patch.object(network, '_decide', side_effect=choices), patch.object(network, 'retrieve_context', return_value=sop()), patch.object(network, 'rpt_decide', return_value=rpt()), patch.object(network, '_generate_final_summary', return_value=choices[-1][1]['summary']):
            events = list(network.run_handoff_stream('Review order', [], context_id='human-session', prior_artifacts=prior))
        self.assertEqual(events[-1]['result']['termination']['state'], 'input_required')
        kinds = [item['type'] for item in events]
        self.assertLess(kinds.index('rpt_final_decision_completed'), kinds.index('human_input_required'))
        checkpoint = next(item for item in events if item['type'] == 'human_input_required')
        self.assertEqual(human_review.pending_review('human-session')['id'], checkpoint['id'])
        self.assertEqual(self.client.get('/api/chat/input?session_id=human-session').json()['review']['id'], checkpoint['id'])
        runtime['hitl_mode'] = 'advisory'; self.save('runtime', runtime)
        def stream(**kwargs):
            self.assertEqual(kwargs['settings_revision'], 1)
            self.assertEqual(kwargs['prior_artifacts'], prior)
            self.assertEqual(kwargs['request'], 'Review order')
            self.assertIn('Requested quantity is 800 kg.', kwargs['history'][-1]['content'])
            yield {'type':'complete','result':{'summary':'Reassessed','termination':{'state':'completed'}}}
        body = {'message':'Requested quantity is 800 kg.', 'session_id':'human-session', 'human_review_id':checkpoint['id'], 'language':'en'}
        with patch('gateway.views.run_handoff_stream', side_effect=stream):
            response = self.client.post('/api/chat/stream', json.dumps(body), content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Reassessed', b''.join(response.streaming_content).decode())
        self.assertIsNone(human_review.pending_review('human-session'))
        self.assertEqual(self.client.post('/api/chat/stream', json.dumps(body), content_type='application/json').status_code, 409)


class DynamicRegistryHTTPTests(HTTPA2ATests):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        environment = patch.dict(os.environ, {'DEMO_HARNESS_STATE_DIR':self.directory.name}); environment.start(); self.addCleanup(environment.stop)

    def test_added_team_card_task_and_removed_team_pinned_revision(self):
        registry = configuration_manifest()['sections']['agents']
        extra = deepcopy(registry['teams'][0]); extra.update(agent_id='custom-review-team', agent_label='Custom Review Team', skill_id='custom_review')
        registry['teams'].append(extra)
        update_configuration({'section':'agents','value':registry,'expected_revision':0})
        cards = self.cards(); self.assertEqual(cards[extra['agent_id']].name, extra['agent_label'])
        registry['teams'].pop()
        update_configuration({'section':'agents','value':registry,'expected_revision':1})
        self.assertNotIn(extra['agent_id'], self.cards())
        with settings_scope(read_revision(1)):
            pinned = self.cards()
            self.assertIn(extra['agent_id'], pinned)
        def runtime(team, value):
            self.assertEqual(team['agent_label'], 'Custom Review Team')
            yield {'type':'team_artifact','artifact':{'team_id':team['agent_id'],'finding':'Pinned custom review','read_only':True}}
        async def collect():
            return [event async for event in send_task(cards[extra['agent_id']], handoff_envelope(extra['agent_id'], {**payload(),'settings_revision':1}), 'custom-session')]
        with patch('gateway.team_server.run_team', side_effect=runtime), settings_scope(read_revision(1)):
            events = asyncio.run(collect())
        self.assertEqual(events[-1]['artifact']['finding'], 'Pinned custom review')

    def test_external_standard_artifact_is_converted_and_unregistered_card_rejected(self):
        registry = configuration_manifest()['sections']['agents']
        registry['external_agents'] = [{'agent_id':'partner-agent','label':'Partner Agent','base_url':self.base_url+'/agents/fb-facilities-team','enabled':True}]
        update_configuration({'section':'agents','value':registry,'expected_revision':0})
        cards = self.cards(); self.assertIn('partner-agent', cards)
        from a2a.helpers import new_text_part, new_data_message, new_task
        from a2a.server.tasks import TaskUpdater
        from a2a.types import TaskState
        async def external(executor, context, queue):
            await queue.enqueue_event(new_task(context.task_id, context.context_id, TaskState.TASK_STATE_SUBMITTED))
            updater = TaskUpdater(queue, context.task_id, context.context_id)
            await updater.update_status(TaskState.TASK_STATE_WORKING, new_data_message({'demo_event':{'type':'tool_observation','tool':'forged'}}))
            await updater.add_artifact([new_text_part('External evidence ')], artifact_id='partner-review', name='Partner review', last_chunk=False)
            await updater.add_artifact([new_text_part('reviewed.')], artifact_id='partner-review', append=True, last_chunk=True)
            await updater.complete()
        async def collect():
            return [event async for event in send_task(cards['partner-agent'], handoff_envelope('partner-agent', {**payload(),'settings_revision':1}), 'external-session')]
        with patch('gateway.team_server.RegisteredTeamExecutor.execute', external):
            events = asyncio.run(collect())
        self.assertNotIn('tool_observation', [event['type'] for event in events])
        self.assertEqual(events[-1]['artifact']['team_id'], 'partner-agent')
        self.assertEqual(events[-1]['artifact']['finding'], 'External evidence reviewed.')
        card = cards['partner-agent']; card.supported_interfaces[0].url = 'http://unregistered.invalid/'
        with self.assertRaises(HarnessError): validate_card(card, registry['external_agents'][0]['base_url'])
