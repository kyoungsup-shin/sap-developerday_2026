#!/usr/bin/env python3
"""Film the untouched live stream at its natural pace; accelerate idle loading."""
import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright
from record_live_a2a_demo import LIVE_URL, REQUEST, VIEWPORT, OUTPUT_DIR, OBSERVER, write_json
from record_full_a2a_conversation import presentation
from record_streaming_a2a_conversation import render

FOLLOW = r"""
() => {
 const feed=document.querySelector('.chat-feed');
 const clock=()=>performance.now()/1000;
 window.__realtime={start:clock(),mode:'reading',since:clock(),segments:[],messages:[],lastChange:clock()};
 const log=window.__realtime;
 let scheduled=false, current=null, changedAt=clock(), previous='';
 const mode=(value)=>{
  if(value===log.mode)return;
  const now=clock();log.segments.push({start:log.since,end:now,mode:log.mode,speed:log.mode==='loading'?6:1});
  log.since=now;log.mode=value;document.querySelector('#live-speed').style.visibility=value==='loading'?'visible':'hidden';
 };
 const update=()=>{
  scheduled=false;
  const entries=[...feed.children].filter(el=>!el.classList.contains('typing-message'));
  const last=entries.at(-1);if(!last)return;
  entries.forEach((el,index)=>{
   if(!el.dataset.rtId){el.dataset.rtId=String(index);log.messages.push({index,first:clock(),text:el.innerText});}
   const item=log.messages.find(item=>String(item.index)===el.dataset.rtId);item.text=el.innerText;
  });
  const text=last.innerText, cls=last.classList, meta=last.querySelector('.message-meta')?.innerText??'';
  if(last!==current||text!==previous){
   current=last;previous=text;changedAt=clock();log.lastChange=clock();mode('reading');
  }
  let heading='Orchestrator → Operator', words='I’m coordinating the review and gathering the evidence.';
  if(cls.contains('user')){heading='Operator → Orchestrator';words='Please review this purchase request and ask the Teams to verify the evidence.';}
  else if(cls.contains('grounding')){heading='Grounding → Orchestrator';words='Here are the applicable SOPs and the evidence required before a decision.';}
  else if(cls.contains('rptDecision')){heading=text.includes('FINAL RPT')?'Final RPT → Human reviewer':'Initial RPT → Orchestrator';words='Here is the risk, priority, and human-review assessment.';}
  else if(cls.contains('observation')){heading='Orchestrator → Next Team';words='I’m reviewing the returned evidence and deciding what still needs verification.';}
  else if(cls.contains('actor-subagent')){heading=meta.split('·')[1]?.replace(/\s+\d{1,2}:\d{2}.*$/,'').trim()+' → Team';words='Here are my findings, verified records, and unresolved questions.';}
  else if(cls.contains('actor-team')){const name=meta.split('·')[1]?.replace(/\s+\d{1,2}:\d{2}.*$/,'').trim();heading=name+(text.includes('I received')?' → Specialists':' → Orchestrator');words=text.includes('I received')?'I’m assigning the review to the relevant Specialists.':'Here are our combined findings for your next decision.';}
  else if(cls.contains('actor-joule')){heading='Joule Work Agent';words=/unavailable|could not/i.test(text)?'Joule is unavailable in this run. The local Team review continues.':'I’m checking the external Work Agent connection.';}
  else if(text.includes('Retrieving relevant SOP')){heading='Orchestrator → Grounding';words='Please retrieve the procedures and evidence for this request.';}
  else if(text.includes('Evaluating')){heading='Orchestrator → RPT';words='Please assess the evidence available at this stage.';}
  else if(text.includes('Requesting a review from')){heading='Orchestrator → Team';words=text.match(/Requesting a review from[^.]+/)?.[0]+'.';}
  else if(/^Do not purchase|not ready for purchase.*no purchase/i.test(text.replace(/^.*?\n/,''))||text.includes('No order, supplier confirmation')||text.includes('not authorized or executed')||text.includes('Purchase is')){words='The review is read-only. Complete the missing evidence and obtain authorization before placing an order.';}
  document.querySelector('#conversation-bubble b').textContent=heading;
  document.querySelector('#conversation-bubble p').textContent=words;
  document.querySelector('#conversation-guide .progress').textContent='Live conversation · message '+(entries.length-1);
  const area=feed.getBoundingClientRect(), rect=last.getBoundingClientRect();
  // Follow actual incoming messages without pausing or queuing their delivery.
  const overflow=Math.max(0,rect.height-(area.height-130));
  const offset=Math.min(overflow,Math.max(0,clock()-changedAt-1)*150);
  const desired=rect.top-area.top-85+offset;
  if(Math.abs(desired)>2)feed.scrollTop+=desired;
  const target=last.getBoundingClientRect(), source=document.querySelector('#conversation-bubble').getBoundingClientRect();
  const y=Math.max(area.top+22,Math.min(area.bottom-22,target.top+35)), x=Math.min(area.right-8,target.right+3);
  document.querySelector('#conversation-tail path').setAttribute('d','M '+(source.left-18)+' '+(source.top+59)+' Q '+(source.left-55)+' '+y+' '+x+' '+y);
  const dot=document.querySelector('#conversation-tail circle');dot.setAttribute('cx',x);dot.setAttribute('cy',y);
 };
 new MutationObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(update);}}).observe(feed,{childList:true,subtree:true,characterData:true});
 const timer=setInterval(()=>{
  if(clock()-log.lastChange>1.5 && !window.__film.latest.complete)mode('loading');
  update();
 },100);
 log.finish=()=>{clearInterval(timer);mode('reading');const now=clock();log.segments.push({start:log.since,end:now,mode:'reading',speed:1});};
 update();
}
"""

async def main(args):
    run=OUTPUT_DIR/'attempts'/datetime.now().strftime('%Y%m%d-%H%M%S-realtime')
    run.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        try:
            for attempt in range(args.attempts):
                directory=run/f'attempt-{attempt+1}';directory.mkdir()
                context=await browser.new_context(viewport=VIEWPORT,record_video_size=VIEWPORT,record_video_dir=str(directory),locale='en-US',timezone_id='Asia/Seoul')
                await context.add_init_script(OBSERVER)
                page=await context.new_page();video=page.video;origin=time.monotonic()
                try:
                    await page.goto(args.url,wait_until='networkidle',timeout=45000)
                    await presentation(page)
                    await page.add_style_tag(content='.message .message-body{font-size:17px!important;line-height:1.45!important}.chat-feed{padding-bottom:100px!important}')
                    await page.evaluate("""()=>{
                     document.querySelector('#conversation-guide .eyebrow').textContent='LIVE A2A CONVERSATION';
                     document.querySelector('#conversation-guide .context').innerHTML='Actual live stream at its natural pace.<br><br>Speech bubbles explain each exchange. Loading plays at 6×.';
                     const speed=document.createElement('div');speed.id='live-speed';speed.textContent='LOADING · 6×';speed.style.cssText='visibility:hidden;margin-top:22px;color:#624980;font:700 17px Arial;padding:12px 16px;background:#f2e9ff;border-radius:15px';
                     document.querySelector('#conversation-guide').append(speed);
                    }""")
                    await page.locator('.composer textarea').fill(REQUEST)
                    offset=(time.monotonic()-origin)-await page.evaluate('performance.now()/1000')
                    await page.evaluate(FOLLOW)
                    await page.get_by_role('button',name='Run harness →',exact=True).click()
                    await page.evaluate("()=>document.body.classList.add('full-walk')")
                    print('Native live stream started. No reading pauses or packet buffering.',flush=True)
                    deadline=time.monotonic()+180;last_count=0
                    while time.monotonic()<deadline:
                        state=await page.evaluate('()=>({complete:window.__film.latest.complete,error:window.__film.error,count:window.__realtime.messages.length})')
                        if state['error']:raise RuntimeError(state['error'])
                        if state['count']!=last_count:
                            last_count=state['count'];print(f'Live messages: {last_count}',flush=True)
                        if state['complete']:break
                        await page.wait_for_timeout(200)
                    else:raise TimeoutError('No final state within 180 seconds')
                    elapsed=time.monotonic()-origin
                    await page.wait_for_timeout(3000)
                    await page.evaluate('()=>window.__realtime.finish()')
                    log=await page.evaluate('()=>JSON.parse(JSON.stringify(window.__realtime))')
                    for s in log['segments']:s['start']+=offset;s['end']+=offset
                    log['url']=args.url;log['request']=REQUEST;log['native_run_seconds']=elapsed
                    log['termination']=state['complete'].get('result',{}).get('termination',{})
                    if log['termination'].get('state') not in {'completed','input_required'}:raise RuntimeError(str(log['termination']))
                    log['final_summary']=state['complete'].get('result',{}).get('summary','')
                    log['event_kinds']=await page.evaluate('()=>window.__film.events')
                    count=await page.locator('.chat-feed > :not(.typing-message)').count()
                    if count!=len(log['messages']):raise RuntimeError('Message observation coverage mismatch')
                    log['coverage']=f'{count-1}/{count-1} conversation messages'
                    await page.screenshot(path=str(directory/'final.png'))
                    write_json(directory/'realtime.json',log)
                except Exception as error:
                    await page.screenshot(path=str(directory/'failure.png'));write_json(directory/'failure.json',{'error':str(error)});await context.close();print(str(error),flush=True);continue
                await context.close();raw=Path(await video.path())
                output=OUTPUT_DIR/'live-a2a-harness-realtime.mp4'
                media=render(raw,output,log,directory)
                write_json(directory/'realtime.json',log)
                write_json(OUTPUT_DIR/'latest-realtime.json',{'video':str(output),'raw_video':str(raw),'conversation_log':str(directory/'realtime.json'),'coverage':log['coverage'],'media':media})
                print(f'Created {output}; {media["format"]["duration"]}s; native run {elapsed:.1f}s; {log["coverage"]}',flush=True)
                return 0
        finally:await browser.close()
    return 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=LIVE_URL)
    parser.add_argument('--attempts',type=int,choices=(1,2,3),default=2)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
