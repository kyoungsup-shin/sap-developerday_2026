#!/usr/bin/env python3
"""Record real live Harness evidence and cut readable scenes into a 1080p MP4."""
import argparse
import asyncio
import json
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

LIVE_URL = "https://a2a-demo.dbb6c31.kyma.ondemand.com/"
REQUEST = "Please purchase a CIP pump mechanical seal kit."
VIEWPORT = {"width": 1920, "height": 1080}
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "demo-video"

# Observe a clone of the real SSE response. The app consumes its own stream
# normally; no requests, routing decisions, or results are simulated.
OBSERVER = r"""
(() => {
 window.__film={events:[],latest:{},error:null};
 const original=window.fetch.bind(window);
 window.fetch=async (...args)=>{
  const response=await original(...args);
  if(String(args[0]?.url??args[0]).includes('/api/chat/stream')&&response.ok&&response.body){
   const reader=response.clone().body.getReader();
   (async()=>{
    let buffer=''; const decoder=new TextDecoder();
    while(true){
     const part=await reader.read(); if(part.done)break;
     buffer+=decoder.decode(part.value,{stream:true});
     buffer=buffer.replace(/\r\n/g,'\n');
     const packets=buffer.split('\n\n'); buffer=packets.pop()??'';
     for(const packet of packets){
      const kind=packet.match(/^event:\s*(.+)$/m)?.[1];
      const raw=packet.match(/^data:\s*(.+)$/m)?.[1];
      if(!kind||!raw)continue;
      try{const data=JSON.parse(raw);window.__film.events.push(kind);
       window.__film.latest[kind]=data;
       if(kind==='error')window.__film.error=data.message??'Stream error';
      }catch{}
     }
    }
   })().catch(error=>window.__film.error=String(error));
  }
  return response;
 };
})();
"""

CSS = """
html {font-size:21px !important;}
.studio-layout,.studio-layout.expanded {grid-template-columns:62px minmax(0,1fr) 520px !important;height:calc(100vh - 166px) !important;}
.studio-rail .rail-item b {display:none;}
.studio-chat {padding:20px 30px 12px !important;}
.studio-chat>.chat-feed,.studio-chat>.composer,.studio-chat>.console-heading,.studio-chat>.session-line {width:100% !important;max-width:1160px;}
.chat-feed {scroll-behavior:auto !important;padding:18px 8px 100px !important;}
.message {max-width:98% !important;}
.message>div:last-child {min-width:0;width:100%;}
.message .message-body {font-size:19px !important;line-height:1.55 !important;padding:16px 20px;}
.message-meta {font-size:14px !important;}
.message-body h1,.message-body h2,.message-body h3 {font-size:21px !important;}
.message-body table,.message-tool-call pre,.message-tool-call table {font-size:15px !important;}
.message-tool-call summary,.message-tool-call summary strong {font-size:16px !important;white-space:normal !important;}
.grounding-result,.rpt-result {width:100% !important;max-width:100% !important;}
.grounding-result__preview {font-size:17px !important;line-height:1.5;}
.graph-node b {font-size:14px !important;white-space:normal !important;line-height:1.25;}
.graph-node small {font-size:12px !important;white-space:normal !important;}
.graph-team-list {max-height:none !important;}
.graph-node.team:not(.active) {opacity:.48;}
.graph-node.team:not(.active) small {display:none;}
.config-panel {padding:20px 16px !important;}
.film-focus {outline:3px solid #708b4f !important;outline-offset:4px;border-radius:10px;}
body.film-running .composer {display:none !important;}
#film-footer {position:fixed;bottom:0;left:0;right:0;height:102px;background:#211e1a;color:#fffaf2;z-index:2147483647;pointer-events:none;padding:17px 48px;box-sizing:border-box;display:flex;gap:24px;align-items:center;}
#film-number {color:#cfe2a8;font:700 26px sans-serif;min-width:60px;}
#film-title {font:600 29px/1.2 sans-serif;}
#film-detail {margin-top:7px;font:400 18px/1.3 sans-serif;color:#ddd4c5;}
"""


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def presentation(page):
    await page.add_style_tag(content=CSS)
    await page.evaluate("""()=>{
      document.querySelector('#film-footer')?.remove();
      const footer=document.createElement('div');footer.id='film-footer';
      footer.innerHTML='<div id="film-number"></div><div><div id="film-title"></div><div id="film-detail"></div></div>';
      document.body.append(footer);window.__filmPinned=null;
      window.__filmFollow=()=>{
       const feed=document.querySelector('.chat-feed');if(!feed)return;
       const target=window.__filmPinned;
       if(target?.isConnected){feed.scrollTop+=target.getBoundingClientRect().top-feed.getBoundingClientRect().top-14;}
       else if(document.body.classList.contains('film-running'))feed.scrollTop=feed.scrollHeight;
      };
      new MutationObserver(window.__filmFollow).observe(document.querySelector('#root'),{childList:true,subtree:true,characterData:true});
    }""")


async def event(page, kinds, timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=await page.evaluate("()=>({events:window.__film.events,error:window.__film.error})")
        if state['error']:
            raise RuntimeError("Live stream: " + str(state['error']))
        for kind in kinds:
            if kind in state['events']:
                return kind
        await page.wait_for_timeout(250)
    raise TimeoutError("Live event missing: " + ", ".join(kinds))


async def scene(page, target, log, directory, origin, key, title, detail, seconds, bottom=False):
    await page.evaluate("""()=>{
      document.querySelectorAll('.film-focus').forEach(e=>e.classList.remove('film-focus'));
      window.__filmPinned=null;
    }""")
    if target is not None:
        await target.wait_for(state='attached',timeout=20000)
        await target.evaluate("""(element,bottom)=>{
          element.classList.add('film-focus');window.__filmPinned=bottom?null:element;
          const feed=document.querySelector('.chat-feed');
          if(feed){const rect=element.getBoundingClientRect(),area=feed.getBoundingClientRect();
            feed.scrollTop+=bottom?rect.bottom-area.bottom+28:rect.top-area.top-14;}
        }""",bottom)
    number=str(len(log['scenes'])+1).zfill(2)
    await page.evaluate("""([number,title,detail])=>{
      document.querySelector('#film-number').textContent=number;
      document.querySelector('#film-title').textContent=title;
      document.querySelector('#film-detail').textContent=detail;
    }""",[number,title,detail])
    await page.wait_for_timeout(650)
    start=time.monotonic()-origin
    await page.screenshot(path=str(directory/f'{number}-{key}.png'))
    await page.wait_for_timeout(seconds*1000)
    log['scenes'].append({'key':key,'title':title,'start':start,'end':time.monotonic()-origin})
    print(f'Scene {number}: {title}',flush=True)


async def record_attempt(browser,url,directory):
    context=await browser.new_context(viewport=VIEWPORT,record_video_size=VIEWPORT,
        record_video_dir=str(directory),locale='en-US',timezone_id='Asia/Seoul')
    await context.add_init_script(OBSERVER)
    origin=time.monotonic()
    page=await context.new_page();video=page.video
    log={'url':url,'request':REQUEST,'scenes':[]}
    async def shot(target,key,title,detail,seconds,bottom=False):
        await scene(page,target,log,directory,origin,key,title,detail,seconds,bottom)
    try:
        await page.goto(url,wait_until='networkidle',timeout=45000)
        await page.get_by_role('link',name='◈ Harness guide').click()
        await page.get_by_text('Receive the field request safely',exact=True).wait_for()
        await presentation(page)
        await shot(None,'intro','Live A2A Harness',
            'One equipment request. SOP grounding, specialist evidence, and a governed outcome.',5)
        await page.get_by_role('link',name='← Back to console').click()
        await page.locator('.composer textarea').wait_for()
        if not await page.locator('#film-footer').count():await presentation(page)
        await page.locator('.composer textarea').fill(REQUEST)
        await shot(page.locator('.composer'),'request','Review a CIP pump seal-kit purchase',
            'The operator submits a request for evidence-based review.',4)
        await page.get_by_role('button',name='Run harness →',exact=True).click()
        await page.evaluate("()=>document.body.classList.add('film-running')")
        # Exact result selectors, rather than static labels anywhere in the DOM.
        await page.locator('.message.grounding').first.wait_for(state='attached',timeout=100000)
        await shot(page.locator('.message.grounding').first,'grounding','SOP evidence verified',
            'Grounding retrieves applicable procedures before any Team review.',5)
        await page.locator('.message.rptDecision').first.wait_for(state='attached',timeout=100000)
        await shot(page.locator('.message.rptDecision').first,'initial-rpt','Initial RPT assessment',
            'Read the handoff recommendation and its risk and priority assessment.',5)
        await event(page,('delegation_selected',),150)
        team=page.locator('.message.actor-team:not(.typing-message)').first
        await shot(team,'team','A2A Team handoff',
            'The Team receives the Orchestrator task and selects its Specialists.',5)
        await event(page,('subagent_message_delta',),150)
        tools=page.locator('.message-tool-call')
        await tools.first.wait_for(state='attached',timeout=60000)
        evidence=tools.filter(has_text='retrieve_business_evidence')
        tool=evidence.first if await evidence.count() else tools.first
        await tool.locator('summary').click()
        await shot(tool,'tool','Authorized evidence tool',
            'Inspect the actual tool input and returned business records.',6)
        output=tool.locator('section').filter(has_text='OUTPUT').last
        await shot(output,'tool-output','Evidence returned to the Specialist',
            'Record identifiers and read-only results support the assessment.',5)
        await tool.locator('summary').click()
        await event(page,('artifact_received',),150)
        specialist=page.locator('.message.actor-subagent:not(.typing-message)').first
        await shot(specialist,'specialist','Specialist review',
            'The Specialist explains verified facts and the evidence still required.',5)
        synthesis=page.locator('.message.actor-team:not(.typing-message)').filter(
            has_not_text='I received the Orchestrator').first
        await shot(synthesis,'synthesis','Team synthesis',
            'The Team returns a combined assessment to the Orchestrator.',5)
        await event(page,('complete',),240)
        result=await page.evaluate('()=>window.__film.latest.complete')
        summary=str(result.get('result',{}).get('summary','')).strip()
        if not summary:raise RuntimeError('The live run did not produce a final summary')
        visible_summary=re.sub(r'[*_#]', '', summary)
        final=page.locator('.message.actor-orchestrator:not(.observation)').filter(has_text=visible_summary[:65]).last
        await shot(final,'final-summary','Final outcome and verified figures',
            'Read the actual answer: equipment, availability, quote, lead time, and unresolved inputs.',9)
        await shot(final,'next-action','The next action belongs to an authorized person',
            'Complete the required evidence and follow the approval process. No purchase was executed.',6,bottom=True)
        final_rpt=page.locator('.message.rptDecision').filter(has_text='FINAL RPT').last
        await shot(final_rpt,'final-rpt','Final RPT assessment',
            'Assess accumulated evidence and the human-review requirement.',5)
        log['final_summary']=summary
        log['termination']=result.get('result',{}).get('termination',{})
        log['event_kinds']=await page.evaluate('()=>[...new Set(window.__film.events)]')
    except Exception as error:
        log['error']=f'{type(error).__name__}: {error}'
        await page.screenshot(path=str(directory/'failure.png'))
        log['page_tail']=(await page.locator('body').inner_text())[-3000:]
        log['event_kinds']=await page.evaluate('()=>[...new Set(window.__film?.events??[])]')
        raise
    finally:
        write_json(directory/'attempt.json',log)
        await context.close()
    return Path(await video.path()),log


def make_mp4(raw,output,scenes):
    # Keep selected scenes at normal speed. Remove all intervening waits/scrolls.
    chains=[]
    for index,item in enumerate(scenes):
        chains.append(f"[0:v]trim=start={item['start']:.3f}:end={item['end']:.3f},setpts=PTS-STARTPTS[v{index}]")
    chains.append(''.join(f'[v{i}]' for i in range(len(scenes)))+
        f'concat=n={len(scenes)}:v=1:a=0,fps=25,format=yuv420p[video]')
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(raw),'-f','lavfi','-i',
        'anullsrc=channel_layout=stereo:sample_rate=48000','-filter_complex',';'.join(chains),
        '-map','[video]','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','18',
        '-c:a','aac','-shortest','-movflags','+faststart',str(output)],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'format=duration,size:stream=codec_name,width,height','-of','json',str(output)],text=True))
    seconds=float(probe['format']['duration'])
    if not 45<=seconds<=75:raise RuntimeError(f'Edited video is {seconds:.2f}s; expected 45–75s')
    return probe


async def main_async(args):
    if not 1<=args.attempts<=3:raise ValueError('--attempts must be between 1 and 3')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('ffmpeg and ffprobe are required')
    run_dir=OUTPUT_DIR/'attempts'/datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=not args.headed)
        try:
            for attempt in range(1,args.attempts+1):
                directory=run_dir/f'attempt-{attempt}';directory.mkdir()
                try:
                    raw,log=await record_attempt(browser,args.url,directory)
                    output=OUTPUT_DIR/'live-a2a-harness-demo-v2.mp4'
                    probe=make_mp4(raw,output,log['scenes'])
                    write_json(OUTPUT_DIR/'latest-run-v2.json',{
                        'raw_video':str(raw),'final_video':str(output),'attempt_log':log,'media':probe})
                    print(f"Created {output} ({probe['format']['duration']} seconds)",flush=True)
                    return 0
                except Exception as error:
                    print(f'Attempt {attempt}: {type(error).__name__}: {error}',flush=True)
        finally:await browser.close()
    return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=LIVE_URL)
    parser.add_argument('--attempts',type=int,default=2)
    parser.add_argument('--headed',action='store_true')
    raise SystemExit(asyncio.run(main_async(parser.parse_args())))
