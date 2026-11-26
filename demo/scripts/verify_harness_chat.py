"""Check presentation of collaboration, human input and consecutive Chat runs.

Uses mocked SSE only; never sends business requests or saves user Chat.
"""
import argparse
import asyncio
import json
from playwright.async_api import async_playwright, expect

parser=argparse.ArgumentParser(); parser.add_argument('--base-url',default='http://localhost:5173'); args=parser.parse_args()
async def main():
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(); page=await browser.new_page()
        calls=[]; state={'pending':None}
        await page.route('**/api/chat/latest',lambda route:route.fulfill(json={'messages':[]}))
        await page.route('**/api/chat/input?**',lambda route:route.fulfill(json={'review':state['pending']}))
        async def stream(route):
            body=route.request.post_data_json; calls.append(body); n=len(calls)
            identity={'agent_id':'fb-facilities-team','agent_label':'Facilities Management Team','handoff_id':'handoff-'+str(n),'step':1}
            checkpoint={'id':'a'*32,'handoff_mode':'request_evidence'} if n==1 else None
            state['pending']=checkpoint
            entries=[('session',{'session_id':'mock-session'}),('team_handoff_started',identity),('delegation_started',identity),
                ('delegation_selected',{**identity,'delegations':['Facilities Engineering Specialist'],'delegation_goals':[{'agent':'Facilities Engineering Specialist','goal':'Verify equipment evidence.'}]}),
                ('subagent_started',{**identity,'subagent_label':'Facilities Engineering Specialist','sub_step':1}),
                ('tool_observation',{**identity,'subagent_label':'Facilities Engineering Specialist','tool':'retrieve_business_evidence','arguments':{'context_id':'CTX-EQP-CIP-SEAL'},'domains':['facility'],'result':{'state':'found','read_only':True}}),
                ('subagent_message_delta',{**identity,'subagent_label':'Facilities Engineering Specialist','stream_id':'specialist-review','delta':'Specialist evidence '+str(n)}),
                ('team_message_delta',{**identity,'stream_id':'team-review','delta':'Team synthesis '+str(n)}),
                ('orchestrator_message_delta',{'stream_id':'final-summary','delta':'Final answer '+str(n)}),
                ('rpt_final_decision_completed',{'decision':{'next_agent':'fb-facilities-team','handoff_mode':'request_evidence' if n==1 else 'delegate_now','risk':'low','priority':'1','grounding_used':True,'team_rankings':[]}})]
            if checkpoint:entries.append(('human_input_required',checkpoint))
            entries.append(('complete',{'result':{'summary':'Final answer '+str(n),'termination':{'state':'input_required' if checkpoint else 'completed'},'human_review':checkpoint}}))
            await route.fulfill(content_type='text/event-stream',body=''.join('event: '+kind+'\ndata: '+json.dumps(data)+'\n\n' for kind,data in entries))
        await page.route('**/api/chat/stream',stream)
        await page.goto(args.base_url)
        await page.locator('.composer textarea').fill('Review the documented kit.')
        await page.get_by_role('button',name='Run harness →',exact=True).click()
        await expect(page.get_by_text('Final answer 1',exact=True)).to_be_visible()
        await expect(page.get_by_role('button',name='Submit input & reassess →',exact=True)).to_be_visible()
        bodies=await page.locator('.message').all_text_contents()
        sequence=[next(i for i,value in enumerate(bodies) if marker in value) for marker in ('I received','Specialist evidence 1','Team synthesis 1','Final answer 1')]
        assert sequence==sorted(sequence),sequence
        assert sum('I received' in value for value in bodies)==1
        assert not any('A2A HANDOFF' in value for value in bodies)
        await page.locator('.composer textarea').fill('Requested evidence is available.')
        await page.get_by_role('button',name='Submit input & reassess →',exact=True).click()
        await expect(page.get_by_text('Final answer 2',exact=True)).to_be_visible()
        await expect(page.get_by_text('Final answer 1',exact=True)).to_be_visible()
        assert calls[1]['human_review_id']=='a'*32
        assert calls[1]['session_id']=='mock-session'
        await expect(page.get_by_role('button',name='Run harness →',exact=True)).to_be_visible()
        assert await page.get_by_text('Final answer 1',exact=True).count()==1
        assert await page.get_by_text('Final answer 2',exact=True).count()==1
        print('PASS: Team receipt → Specialist Tool/review → Team synthesis → Orchestrator; human-input submission; separate final answers for consecutive runs.')
        await browser.close()
asyncio.run(main())
