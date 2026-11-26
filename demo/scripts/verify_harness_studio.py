"""Browser verification against a running demo; restores settings after each test.

Run with a Python environment providing Playwright and Chromium.
Business Chat is stubbed and latest-Chat writes are intercepted.
"""
import argparse
import asyncio
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen
from playwright.async_api import async_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://localhost:5173')
parser.add_argument('--output-dir', type=Path, default=Path('/tmp/harness-studio-verification'))
args = parser.parse_args()
args.output_dir.mkdir(parents=True, exist_ok=True)

def api(path, body=None):
    request = Request(args.base_url + path, data=json.dumps(body).encode() if body is not None else None,
                      headers={'Content-Type':'application/json','Origin':args.base_url.rstrip('/')})
    with urlopen(request, timeout=60) as response: return json.load(response)

async def verify_evaluation_navigation(browser, findings):
    """Use a simulated running evaluation to test navigation without provider calls."""
    page = await browser.new_page(viewport={'width':1440,'height':1000})
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    run = {'id':'navigation-test','state':'running','revision':1,'started_at':0,
           'scenario_count':5,'report':{'overall_score':0,'scenarios':[]}}
    polls = 0

    async def result(route):
        nonlocal polls
        polls += 1
        await route.fulfill(json=run)

    await page.route('**/api/chat/latest', lambda route: route.fulfill(json={'session_id':'browser-only','messages':[]}))
    await page.route('**/api/harness/evaluations', lambda route: route.fulfill(json={'runs':[run]}))
    await page.route('**/api/harness/evaluations/navigation-test', result)
    await page.goto(args.base_url)
    await page.get_by_role('button',name='Harness Studio',exact=True).click()
    studio = page.locator('.harness-studio')
    await studio.get_by_role('button',name='Evaluation',exact=True).click()
    await expect(studio.get_by_role('heading',name='Live evaluation',exact=True)).to_be_visible()
    checkbox = studio.get_by_role('checkbox').first
    await checkbox.uncheck()
    await studio.get_by_text('Evaluation settings',exact=True).click()
    await studio.get_by_label('Scenario timeout (seconds)',exact=True).fill('302')
    await studio.get_by_role('button',name='Back to settings',exact=True).click()
    await studio.get_by_role('button',name='Tools',exact=True).click()
    await expect(studio.get_by_role('textbox',name='LLM Tool description',exact=True)).to_be_visible()
    prior_polls = polls
    run['state'] = 'completed'
    await page.wait_for_timeout(2500)
    assert polls > prior_polls,'Evaluation polling stopped while hidden'
    await studio.get_by_role('button',name='Back to settings',exact=True).click()
    await studio.get_by_role('button',name='Evaluation',exact=True).click()
    await expect(studio.get_by_role('heading',name='Evaluation completed',exact=True)).to_be_visible()
    await expect(checkbox).not_to_be_checked()
    await expect(studio.get_by_label('Scenario timeout (seconds)',exact=True)).to_have_value('302')
    await expect(studio.get_by_role('combobox',name='Run history',exact=True)).to_have_value('navigation-test')
    assert not errors,errors
    findings.append({'passed':True,'checks':['evaluation draft and scenario selection retained','run history retained','hidden evaluation polling and completion']})
    await page.close()

async def main():
    original = api('/api/harness/configuration')
    prompt_original = api('/api/harness/prompts')
    findings = []
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        for width in (1440, 900, 390):
            page = await browser.new_page(viewport={'width':width,'height':1000})
            errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
            await page.route('**/api/chat/latest', lambda route: route.fulfill(json={'session_id':'browser-only','messages':[{'id':'saved','role':'assistant','body':'Saved Chat retained.','time':'READY'}]}))
            await page.goto(args.base_url)
            await expect(page.get_by_text('Saved Chat retained.', exact=True)).to_be_visible()
            await page.get_by_role('button', name='Harness Studio', exact=True).click()
            studio=page.locator('.harness-studio')
            card_names=('Agents & A2A','Prompts & Models','Tools','Business Data','Grounding','Runtime','RPT Decision','Joule','Evaluation')
            grid=studio.locator('.harness-studio__cards')
            await expect(grid.get_by_role('button')).to_have_count(9)
            await expect(studio.get_by_role('tab')).to_have_count(0)
            await expect(studio.locator('.harness-editor:visible')).to_have_count(0)
            columns=await grid.evaluate('(el) => getComputedStyle(el).gridTemplateColumns.split(" ").length')
            assert columns == (3 if width == 1440 else 2 if width == 900 else 1),(width,columns)
            assert await grid.locator('svg, img').count()==0
            assert len(set(await grid.locator('.harness-studio__card-title').evaluate_all('(els) => els.map(el => getComputedStyle(el).fontSize)')))==1
            await page.screenshot(path=str(args.output_dir/f'studio-cards-{width}.png'),full_page=True)

            async def open_setting(name):
                back=studio.get_by_role('button',name='Back to settings',exact=True)
                if await back.is_visible():
                    await back.click()
                await expect(grid).to_be_visible()
                card=grid.get_by_role('button',name=name,exact=True)
                await card.focus()
                await card.press('Enter')
                await expect(grid).to_be_hidden()
                await expect(studio.get_by_role('heading',name=name,exact=True,level=1)).to_be_focused()

            for name in card_names:
                await open_setting(name)
                await expect(studio.locator('.harness-editor:visible')).to_have_count(1)
                assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth'),(width,name,'page overflow')
                await studio.get_by_role('button',name='Back to settings',exact=True).click()
                await expect(grid.get_by_role('button',name=name,exact=True)).to_be_focused()
                await expect(studio.locator('.harness-editor:visible')).to_have_count(0)
            if width == 900:
                assert not errors,errors
                findings.append({'viewport':width,'passed':True,'checks':['nine direct editors','two-column cards','keyboard entry and return focus','no page overflow']})
                await page.close()
                continue
            try:
                await open_setting('Prompts & Models')
                editor=studio.get_by_role('region',name='Prompt and model editor')
                await expect(editor.get_by_role('textbox',name='System prompt',exact=True)).to_be_visible()
                agent_nav=editor.locator('.harness-editor__selection-nav[aria-label="Agent selection"]')
                await expect(agent_nav).to_be_visible()
                assert await editor.locator('select').count()==1,'Agent dropdown should be replaced; only model deployment remains'
                agent_buttons=agent_nav.get_by_role('button')
                assert await agent_buttons.count() >= 2
                await expect(agent_buttons.first).to_have_attribute('aria-pressed','true')
                initial=await editor.get_by_role('textbox',name='System prompt',exact=True).input_value()
                await editor.get_by_role('textbox',name='System prompt',exact=True).fill(initial+'\nUse clear English source citations.')
                await agent_buttons.nth(1).focus()
                await agent_buttons.nth(1).press('Enter')
                await expect(agent_buttons.nth(1)).to_have_attribute('aria-pressed','true')
                await agent_buttons.first.click()
                await expect(editor.get_by_role('textbox',name='System prompt',exact=True)).to_have_value(initial+'\nUse clear English source citations.')
                await open_setting('Tools')
                await expect(studio.get_by_role('textbox',name='LLM Tool description',exact=True)).to_be_visible()
                await open_setting('Prompts & Models')
                await expect(editor.get_by_role('textbox',name='System prompt',exact=True)).to_have_value(initial+'\nUse clear English source citations.')
                await page.get_by_role('button',name='Chat',exact=True).click()
                await expect(page.get_by_text('Saved Chat retained.',exact=True)).to_be_visible()
                await page.get_by_role('button',name='Harness Studio',exact=True).click()
                await expect(editor.get_by_role('textbox',name='System prompt',exact=True)).to_have_value(initial+'\nUse clear English source citations.')
                await editor.get_by_role('button',name='Compare changes',exact=True).click()
                await expect(editor.get_by_role('heading',name='Your draft',exact=True)).to_be_visible()
                await editor.get_by_role('button',name='Edit',exact=True).click()
                await editor.get_by_role('button',name='Save settings',exact=True).click()
                await expect(editor.locator('.harness-editor__success')).to_contain_text('Saved revision',timeout=15000)
                assert api('/api/harness/prompts')['agents'][0]['prompt'].endswith('Use clear English source citations.')
                await open_setting('Tools')
                description=studio.get_by_role('textbox',name='LLM Tool description',exact=True)
                tool_draft=(await description.input_value())+' Use verified Context IDs.'
                await description.fill(tool_draft)
                await open_setting('Runtime')
                await studio.get_by_label('max handoffs',exact=True).fill('2')
                await open_setting('Tools')
                await expect(description).to_have_value(tool_draft)
                await open_setting('Runtime')
                await expect(studio.get_by_label('max handoffs',exact=True)).to_have_value('2')
                await studio.get_by_role('button',name='Discard changes',exact=True).click()
                await open_setting('Tools')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                assert api('/api/tools')[0]['description'].endswith('Use verified Context IDs.')
                await open_setting('Business Data')
                cell=studio.get_by_label('NAME row 1',exact=True)
                value=await cell.input_value(); await cell.fill(value+' browser-test')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                assert api('/api/harness/configuration')['sections']['data']['business_context.csv'][0]['NAME'].endswith('browser-test')
                await open_setting('Grounding')
                prompt=studio.get_by_role('textbox',name='Prompt text',exact=True)
                await prompt.fill((await prompt.input_value())+'\nRetain verified source IDs.')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                await open_setting('Runtime')
                limit=studio.get_by_label('max handoffs',exact=True)
                await limit.fill('0')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__error')).to_contain_text('positive integer')
                await expect(limit).to_have_value('0')
                await studio.get_by_role('button',name='Discard changes',exact=True).click()
                await limit.fill('2')
                saved=api('/api/harness/configuration')
                api('/api/harness/configuration',{'section':'runtime','value':saved['sections']['runtime'],'expected_revision':saved['revision']})
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__error')).to_contain_text('changed since')
                await expect(limit).to_have_value('2')
                await studio.get_by_role('button',name='Reload saved version',exact=True).click()
                await expect(limit).to_have_value(str(original['sections']['runtime']['max_handoffs']))
                await limit.fill('2')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                assert api('/api/harness-profile')['runtime']['max_handoffs']==2
                await open_setting('RPT Decision')
                instructions=studio.get_by_role('textbox',name='Instructions',exact=True).first
                await instructions.fill((await instructions.input_value())+' Preserve the source state.')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                await open_setting('Joule')
                await expect(studio.get_by_label('Solution ID',exact=True)).to_be_visible()
                await studio.get_by_role('button',name='Check saved connection',exact=True).click()
                await expect(studio.get_by_role('status')).to_contain_text('Connection could not be verified')
                await open_setting('Evaluation')
                await expect(studio.get_by_role('button',name=re.compile('Run selected scenarios|Evaluation running'))).to_be_visible()
                await studio.get_by_text('Evaluation settings',exact=True).click()
                await studio.get_by_label('Scenario timeout (seconds)',exact=True).fill('301')
                await studio.get_by_role('button',name='Save evaluation settings',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved evaluation')
                assert api('/api/harness/configuration')['sections']['evaluation']['timeout_seconds']==301
                await open_setting('Agents & A2A')
                team_nav=studio.locator('.harness-editor__selection-nav[aria-label="Team selection"]')
                await expect(team_nav).to_be_visible()
                assert await studio.locator('.harness-config select').count()==0,'Team dropdown should be replaced'
                team_buttons=team_nav.locator('.harness-editor__selection-item')
                assert await team_buttons.count() >= 2
                await expect(team_buttons.first).to_have_attribute('aria-pressed','true')
                tags=studio.get_by_label('Skill tags (comma separated)',exact=True)
                await tags.fill('a2a'); await tags.press('End'); await tags.press_sequentially(', custom')
                await expect(tags).to_have_value('a2a, custom')
                await team_buttons.nth(1).click()
                await expect(team_buttons.nth(1)).to_have_attribute('aria-pressed','true')
                await team_buttons.first.click()
                await expect(tags).to_have_value('a2a, custom')
                await studio.get_by_role('button',name='Save configuration',exact=True).click()
                await expect(studio.locator('.harness-editor__success:visible')).to_contain_text('Saved revision')
                await studio.get_by_role('button',name='Check Team Card',exact=True).click()
                await expect(studio.get_by_text('Verified Agent Card',exact=True)).to_be_visible()
                assert api('/api/harness/agent-card?agent_id=fb-facilities-team')['verified']
                for tab in card_names:
                    await open_setting(tab)
                    await expect(studio).to_be_visible()
                    assert await studio.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'),(width,tab,'Studio overflow')
                    assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth'),(width,tab,'page overflow')
                if width == 390:
                    await open_setting('Prompts & Models')
                    nav=studio.locator('.harness-editor__selection-nav[aria-label="Agent selection"]')
                    assert await nav.evaluate('(el) => getComputedStyle(el).overflowX') in ('auto','scroll')
                    await open_setting('Agents & A2A')
                    nav=studio.locator('.harness-editor__selection-nav[aria-label="Team selection"]')
                    assert await nav.evaluate('(el) => getComputedStyle(el).overflowX') in ('auto','scroll')
                await page.screenshot(path=str(args.output_dir/f'studio-editor-{width}.png'),full_page=True)
                await studio.get_by_role('button',name='Back to settings',exact=True).click()
                await expect(grid).to_be_visible()
                assert not errors,errors
                findings.append({'viewport':width,'passed':True,'checks':['nine direct editors','3/2/1 card layout','keyboard entry and return focus','draft retention','Prompt/Tool/Data/Grounding/Runtime/RPT/Evaluation save','conflict preservation','invalid-save preservation','Card check','comma input','Chat retained','no page overflow','no JavaScript errors']})
            finally:
                saved=api('/api/harness/configuration')
                for section,value in original['sections'].items():
                    if saved['sections'][section]!=value:
                        saved=api('/api/harness/configuration',{'section':section,'value':value,'expected_revision':saved['revision']})
                saved_prompt=api('/api/harness/prompts'); baseline=prompt_original['agents'][0]
                if saved_prompt['agents'][0]['prompt']!=baseline['prompt']:
                    api('/api/harness/prompts',{'agent_id':'orchestrator','prompt':None if baseline['prompt']==baseline['default_prompt'] else baseline['prompt'],'expected_revision':saved_prompt['revision']})
                await page.close()
        await verify_evaluation_navigation(browser, findings)
        await browser.close()
    (args.output_dir/'browser-report.json').write_text(json.dumps(findings,indent=2))
    print(json.dumps(findings,indent=2))

asyncio.run(main())
