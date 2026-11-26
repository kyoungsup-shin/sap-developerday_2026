#!/usr/bin/env python3
"""Film every message in a real live Harness run, with speech-bubble annotations.

The service completes the real task first. Its actual mounted conversation is
then filmed in chronological order at reading speed; no messages are recreated,
reordered, or selected out. This is a full walkthrough of a recorded live run.
"""
import argparse
import asyncio
import json
import math
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from record_live_a2a_demo import LIVE_URL, REQUEST, VIEWPORT, OUTPUT_DIR, OBSERVER, event, write_json

CSS = """
html {font-size:21px !important;}
.studio-layout,.studio-layout.expanded {grid-template-columns:62px minmax(0,1fr) 420px !important;height:calc(100vh - 64px) !important;}
.studio-rail .rail-item b {display:none;}
.studio-chat {padding:16px 36px 20px !important;}
.studio-chat>.chat-feed,.studio-chat>.console-heading,.studio-chat>.session-line {width:100% !important;max-width:1250px;}
.chat-feed {scroll-behavior:auto !important;padding:18px 12px 600px !important;}
.message {max-width:98% !important;gap:14px;}
.message>div:last-child {min-width:0;width:100%;}
.message .message-body {font-size:19px !important;line-height:1.6 !important;padding:17px 22px;}
.message-meta {font-size:15px !important;}
.message-body h1,.message-body h2,.message-body h3 {font-size:22px !important;}
.message-body table,.message-tool-call table,.message-tool-call pre {font-size:15px !important;}
.message-tool-call summary,.message-tool-call summary strong {font-size:16px !important;white-space:normal !important;}
.grounding-result,.rpt-result {width:100% !important;max-width:100% !important;}
.grounding-result__preview {max-height:none !important;overflow:visible !important;font-size:17px !important;line-height:1.5;}
.observation-result__summary {font-size:17px !important;line-height:1.5;}
body.full-walk .composer {display:none !important;}
.config-panel>* {visibility:hidden !important;}
#conversation-guide {position:fixed;top:105px;right:24px;width:364px;z-index:2147483646;pointer-events:none;font-family:Arial,sans-serif;color:#30293d;}
#conversation-guide .eyebrow {font-size:13px;font-weight:700;letter-spacing:.13em;color:#796c88;margin-bottom:16px;}
#conversation-guide .progress {font-size:15px;color:#796c88;margin-top:26px;}
#conversation-guide .context {font-size:17px;line-height:1.55;color:#756b7d;margin-top:24px;}
#conversation-bubble {position:relative;margin-top:0;background:#f2e9ff;border:2px solid #9d87bd;border-radius:24px;padding:24px 24px 25px;box-shadow:0 8px 22px #46335016;}
#conversation-bubble:before {content:'';position:absolute;left:-19px;top:44px;border-top:15px solid transparent;border-bottom:15px solid transparent;border-right:19px solid #9d87bd;}
#conversation-bubble:after {content:'';position:absolute;left:-15px;top:46px;border-top:13px solid transparent;border-bottom:13px solid transparent;border-right:17px solid #f2e9ff;}
#conversation-bubble b {display:block;font-size:18px;line-height:1.4;margin-bottom:15px;color:#624980;}
#conversation-bubble p {font-size:23px;line-height:1.48;margin:0;}
#conversation-tail {position:fixed;inset:0;width:100%;height:100%;pointer-events:none;z-index:2147483645;}
"""


async def presentation(page):
    await page.add_style_tag(content=CSS)
    await page.evaluate("""()=>{
      const guide=document.createElement('aside');guide.id='conversation-guide';
      guide.innerHTML='<div class="eyebrow">CONVERSATION GUIDE</div><div id="conversation-bubble"><b></b><p></p></div><div class="progress"></div><div class="context">Complete conversation from a real live run.<br><br>Annotations explain the exchange; the original Agent messages appear on the left.</div>';
      document.body.append(guide);
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.id='conversation-tail';
      svg.innerHTML='<path fill="none" stroke="#9d87bd" stroke-width="2" stroke-dasharray="5 6"/><circle r="4" fill="#9d87bd"/>';
      document.body.append(svg);
    }""")


def annotation(meta, classes, text, final_summary):
    actor=re.sub(r'\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)?', '', meta).strip()
    if 'user' in classes:
        return 'Operator → Orchestrator', 'Please review this purchase request and gather the evidence we need.'
    if 'grounding' in classes:
        return 'Grounding → Orchestrator', 'Here are the applicable SOPs and the evidence required before a decision.'
    if 'rptDecision' in classes:
        if 'FINAL RPT' in text:
            return 'Final RPT → Human reviewer', 'Here is the risk and priority assessment based on the completed review.'
        return 'Initial RPT → Orchestrator', 'Here is my initial assessment of the handoff conditions.'
    if 'observation' in classes:
        return 'Orchestrator → Next Team', 'I’m checking what we have learned and what the next Team still needs to verify.'
    if 'actor-joule' in classes:
        if 'could not' in text.lower() or 'unavailable' in text.lower():
            return 'Joule connection status', 'Joule is unavailable in this run. The local Team review continues.'
        return 'Orchestrator ↔ Joule', 'I’m checking the external Work Agent connection for this review.'
    if 'actor-subagent' in classes:
        name=actor.partition('·')[2].strip() or 'Specialist'
        return f'{name} → Team', 'Here are my verified records, findings, and the questions that remain unresolved.'
    if 'actor-team' in classes:
        name=actor.partition('·')[2].strip() or 'Team'
        if 'I received' in text:
            return f'{name} → Specialists', 'I’ve received the task. Here is what each Specialist should check.'
        return f'{name} → Orchestrator', 'I’m returning our combined findings so you can decide the next step.'
    if final_summary and final_summary[:45].replace('*','') in text:
        return 'Orchestrator → Operator', 'Here is the combined outcome, the supporting figures, and the next action.'
    if 'Requesting a review from' in text:
        target=text.split('Requesting a review from',1)[1].split('.')[0].strip()
        return f'Orchestrator → {target}', 'Please review this request from your Team’s perspective.'
    if 'Retrieving relevant SOP' in text:
        return 'Orchestrator → Grounding', 'I’ll retrieve the applicable procedures before asking the Teams to review.'
    if 'Evaluating' in text and 'RPT' in text:
        return 'Orchestrator → RPT', 'Please assess the review conditions and the evidence available so far.'
    if 'system-event' in classes:
        return 'Harness activity', 'This event records the next step in the same conversation.'
    return 'Orchestrator → Operator', 'I’ve received your request. I’m coordinating the review and collecting evidence.'


async def bubble(page, heading, text, progress, target=None):
    await page.evaluate("""([heading,text,progress])=>{
      document.querySelector('#conversation-bubble b').textContent=heading;
      document.querySelector('#conversation-bubble p').textContent=text;
      document.querySelector('#conversation-guide .progress').textContent=progress;
    }""",[heading,text,progress])
    if target is not None:
        await target.evaluate("""element=>{
          const area=document.querySelector('.chat-feed').getBoundingClientRect();
          const rect=element.getBoundingClientRect();
          const start=document.querySelector('#conversation-bubble').getBoundingClientRect();
          const y=Math.max(area.top+22,Math.min(area.bottom-22,rect.top+35));
          const x=Math.min(area.right-8,rect.right+3);
          document.querySelector('#conversation-tail path').setAttribute('d',
            'M '+(start.left-18)+' '+(start.top+59)+' Q '+(start.left-55)+' '+y+' '+x+' '+y);
          const circle=document.querySelector('#conversation-tail circle');
          circle.setAttribute('cx',x);circle.setAttribute('cy',y);
        }""")


async def record_attempt(browser, args, directory):
    context=await browser.new_context(viewport=VIEWPORT,record_video_size=VIEWPORT,
        record_video_dir=str(directory),locale='en-US',timezone_id='Asia/Seoul')
    await context.add_init_script(OBSERVER)
    origin=time.monotonic()
    page=await context.new_page();video=page.video
    log={'url':args.url,'request':REQUEST,'messages':[]}
    try:
        await page.goto(args.url,wait_until='networkidle',timeout=45000)
        await page.locator('.composer textarea').fill(REQUEST)
        await page.get_by_role('button',name='Run harness →',exact=True).click()
        print('Real live run started; collecting the complete conversation.',flush=True)
        await event(page,('complete',),360)
        result=await page.evaluate('()=>window.__film.latest.complete')
        termination=result.get('result',{}).get('termination',{})
        if termination.get('state') not in ('completed','input_required'):
            raise RuntimeError('Live run did not complete: '+str(termination))
        summary=result.get('result',{}).get('summary','')
        await page.wait_for_timeout(1000)
        await presentation(page)
        await page.evaluate("()=>document.body.classList.add('full-walk')")
        entries=page.locator('.chat-feed > *')
        count=await entries.count()
        log['message_count']=count
        log['termination']=termination
        log['final_summary']=summary
        log['recording_mode']='Complete chronological walkthrough of actual live-run messages'
        log['walk_start']=time.monotonic()-origin
        for index in range(count):
            target=entries.nth(index)
            classes=await target.get_attribute('class') or ''
            meta=await target.locator('.message-meta').inner_text() if await target.locator('.message-meta').count() else 'Harness event'
            # Expand review sections and all authorized tool results in place.
            await target.evaluate("""element=>{
              element.querySelectorAll('details').forEach(detail=>detail.open=true);
              element.querySelectorAll('pre').forEach(pre=>{
                pre.style.maxHeight='none';pre.style.overflow='visible';pre.style.whiteSpace='pre-wrap';
              });
            }""")
            text=await target.inner_text()
            heading, explanation=annotation(meta,classes,text,summary)
            metrics=await target.evaluate("""element=>{
              const feed=document.querySelector('.chat-feed');
              return {height:element.getBoundingClientRect().height,viewport:feed.clientHeight};
            }""")
            # Overlapping viewport steps ensure every part of every message is
            # shown, including long delegation lists and all tool outputs.
            step=max(200,metrics['viewport']-190)
            offsets=list(range(0,math.ceil(metrics['height']),math.floor(step)))
            words=len(text.split())
            dwell=max(args.min_hold,min(12,words/max(1,len(offsets))/4.2))
            message_start=time.monotonic()-origin
            for part,offset in enumerate(offsets):
                await target.evaluate("""(element,offset)=>{
                  const feed=document.querySelector('.chat-feed');
                  feed.scrollTop+=element.getBoundingClientRect().top-feed.getBoundingClientRect().top-100+offset;
                }""",offset)
                await bubble(page,heading,explanation,
                    f'Message {index+1} / {count} · part {part+1} / {len(offsets)}',target)
                await page.wait_for_timeout(350)
                await page.screenshot(path=str(directory/f'{index+1:03d}-{part+1:02d}.png'))
                await page.wait_for_timeout(dwell*1000)
            log['messages'].append({'index':index+1,'actor':meta,'classes':classes,'text':text,
                'pages':len(offsets),'hold_per_page':round(dwell,2),'start':message_start,
                'end':time.monotonic()-origin,'annotation':{'heading':heading,'text':explanation}})
            print(f'Message {index+1}/{count}: {meta} ({len(offsets)} pages)',flush=True)
        log['walk_end']=time.monotonic()-origin
        if len(log['messages'])!=count:
            raise RuntimeError('Conversation coverage is incomplete')
        if await entries.count()!=count:
            raise RuntimeError('Conversation changed during the walkthrough')
    except Exception as error:
        log['error']=f'{type(error).__name__}: {error}'
        await page.screenshot(path=str(directory/'failure.png'))
        raise
    finally:
        write_json(directory/'conversation.json',log)
        await context.close()
    return Path(await video.path()),log


def render(raw,output,log):
    # One continuous take: no message cuts, no acceleration, and no speech or
    # intermediate handoff omitted. Only pre-walk task processing is removed.
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(raw),'-f','lavfi','-i',
        'anullsrc=channel_layout=stereo:sample_rate=48000','-filter_complex',
        f"[0:v]trim=start={log['walk_start']:.3f}:end={log['walk_end']:.3f},setpts=PTS-STARTPTS,fps=25,format=yuv420p[v]",
        '-map','[v]','-map','1:a:0','-c:v','libx264','-preset','medium','-crf','18',
        '-c:a','aac','-shortest','-movflags','+faststart',str(output)],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'format=duration,size:stream=codec_name,width,height','-of','json',str(output)],text=True))
    return probe


async def main(args):
    if not 1<=args.attempts<=3:raise ValueError('Use 1–3 attempts')
    if not 3<=args.min_hold<=12:raise ValueError('Use 3–12 seconds minimum hold')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        raise RuntimeError('ffmpeg and ffprobe are required')
    run_dir=OUTPUT_DIR/'attempts'/datetime.now().strftime('%Y%m%d-%H%M%S-full')
    run_dir.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=not args.headed)
        try:
            for index in range(args.attempts):
                directory=run_dir/f'attempt-{index+1}';directory.mkdir()
                try:
                    raw,log=await record_attempt(browser,args,directory)
                    output=OUTPUT_DIR/'live-a2a-harness-full-conversation.mp4'
                    media=render(raw,output,log)
                    write_json(OUTPUT_DIR/'latest-full-conversation.json',{
                        'raw_video':str(raw),'video':str(output),'coverage':f"{len(log['messages'])}/{log['message_count']}",
                        'media':media,'conversation_log':str(directory/'conversation.json')})
                    print(f"Created {output}; {len(log['messages'])} messages; {media['format']['duration']} seconds",flush=True)
                    return 0
                except Exception as error:print(f'Attempt {index+1}: {error}',flush=True)
        finally:await browser.close()
    return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=LIVE_URL)
    parser.add_argument('--attempts',type=int,default=2)
    parser.add_argument('--min-hold',type=float,default=4)
    parser.add_argument('--headed',action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
