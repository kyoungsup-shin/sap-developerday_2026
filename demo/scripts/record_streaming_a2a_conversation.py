#!/usr/bin/env python3
"""Record real SSE arrival, with reading pauses and accelerated loading.

Packets and response text are never synthesized. The browser consumes the real
stream in order, pausing delivery while the camera reads a completed message.
The backend continues normally; received/delivered timestamps are retained.
"""
import argparse
import asyncio
import json
import math
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
from record_live_a2a_demo import LIVE_URL, REQUEST, VIEWPORT, OUTPUT_DIR, write_json
from record_full_a2a_conversation import presentation, bubble, annotation

STREAM = r"""
(() => {
 const original = window.fetch.bind(window);
 window.__film = {events:[], latest:{}, error:null, trace:[], done:false};
 window.fetch = async (...args) => {
  const response = await original(...args);
  if (!String(args[0]?.url ?? args[0]).includes('/api/chat/stream') || !response.ok || !response.body) return response;
  const reader=response.body.getReader(), decoder=new TextDecoder(), encoder=new TextEncoder();
  const queue=[]; let ended=false, wake=null, failure=null;
  // Read from the real network independently of the camera's reading pauses.
  (async()=>{
   let buffer='';
   try {
    while(true){
     const part=await reader.read();
     if(part.done)break;
     buffer+=decoder.decode(part.value,{stream:true});buffer=buffer.replace(/\r\n/g,'\n');
     const packets=buffer.split('\n\n');buffer=packets.pop()??'';
     for(const packet of packets)queue.push({packet,received:performance.now()});
     if(wake){wake();wake=null;}
    }
    if(buffer.trim())queue.push({packet:buffer,received:performance.now()});
   } catch(error){failure=String(error);}
   ended=true;if(wake)wake();
  })();
  const body=new ReadableStream({async start(controller){
   try {
    while(!ended || queue.length){
     if(!queue.length){await new Promise(resolve=>wake=resolve);continue;}
     const item=queue.shift(), kind=item.packet.match(/^event:\s*(.+)$/m)?.[1];
     const raw=item.packet.match(/^data:\s*(.+)$/m)?.[1];
     let data={};try{data=JSON.parse(raw??'{}');}catch{}
     if(kind)await window.filmBefore(kind,data);
     controller.enqueue(encoder.encode(item.packet+'\n\n'));
     if(kind){
      window.__film.events.push(kind);window.__film.latest[kind]=data;
      window.__film.trace.push({kind,data,received:item.received,delivered:performance.now()});
      if(kind==='error')window.__film.error=data.message??'Stream error';
      await window.filmAfter(kind,data);
     }
    }
    if(failure)throw Error(failure);
    controller.close();window.__film.done=true;
   }catch(error){window.__film.error=String(error);controller.error(error);window.__film.done=true;}
  }});
  return new Response(body,{status:response.status,statusText:response.statusText,headers:response.headers});
 };
})();
"""

STATIC = {
    'field_handoff_received', 'grounding_started', 'grounding_completed',
    'grounding_failed', 'rpt_decision_started', 'rpt_decision_completed',
    'rpt_decision_failed', 'rpt_final_decision_started',
    'rpt_final_decision_completed', 'rpt_final_decision_failed',
    'joule_card_verification_started', 'joule_card_verified',
    'joule_handoff_started', 'joule_handoff_skipped', 'joule_handoff_failed',
    'joule_artifact_received', 'orchestration_observation',
    'orchestration_decision', 'team_handoff_started', 'delegation_started',
    'delegation_selected', 'team_handoff_failed',
}


class Camera:
    def __init__(self, page, directory, origin):
        self.page, self.directory, self.origin = page, directory, origin
        self.segments, self.messages = [], {}
        self.mode, self.since = 'reading', self.now()
        self.current, self.stream_id = None, None
        self.last_read = None
        self.final_key = None

    def now(self):
        return time.monotonic()-self.origin

    async def mode_to(self, mode):
        if mode == self.mode:
            return
        now=self.now()
        self.segments.append({'start':self.since,'end':now,'mode':self.mode,
                              'speed':6 if self.mode=='loading' else 1})
        self.mode, self.since=mode, now
        await self.page.evaluate("mode=>document.querySelector('#live-speed').style.visibility=mode==='loading'?'visible':'hidden'", mode)

    async def latest(self):
        entries=self.page.locator('.chat-feed > :not(.typing-message)')
        if not await entries.count():return None
        return entries.last

    async def describe(self, target):
        classes=await target.get_attribute('class') or ''
        meta=target.locator('.message-meta')
        actor=await meta.inner_text() if await meta.count() else 'Harness event'
        text=await target.inner_text()
        heading,explanation=annotation(actor,classes,text,'')
        if 'not ready for purchase, and no purchase' in text:
            heading,explanation='Orchestrator → Operator','The evidence is incomplete. No purchase, approval, or system change was performed.'
        if 'Evaluating the completed review' in text:
            heading,explanation='Orchestrator → Final RPT','Please assess the accumulated evidence and the need for human review.'
        key=await target.evaluate("element=>{if(!element.dataset.filmId)element.dataset.filmId=crypto.randomUUID();return element.dataset.filmId;}")
        if key==self.final_key or text.lstrip().startswith('Do not purchase'):
            heading,explanation='Orchestrator → Operator','The review is read-only. Complete the missing evidence and obtain authorization before placing an order.'
        return key,actor,classes,text,heading,explanation

    async def follow(self, target, progress='Live response'):
        _,_,_,_,heading,explanation=await self.describe(target)
        await target.evaluate("""element=>{
          const feed=document.querySelector('.chat-feed');
          feed.scrollTop+=element.getBoundingClientRect().top-feed.getBoundingClientRect().top-100;
        }""")
        await bubble(self.page,heading,explanation,progress,target)

    async def read(self):
        target=await self.latest()
        if target is None:return
        key,actor,classes,text,heading,explanation=await self.describe(target)
        if self.last_read==(key,text):return
        await self.mode_to('reading')
        await target.evaluate("""element=>{
         element.querySelectorAll('details').forEach(detail=>detail.open=true);
         element.querySelectorAll('pre').forEach(pre=>{pre.style.maxHeight='none';pre.style.overflow='visible';pre.style.whiteSpace='pre-wrap';});
        }""")
        key,actor,classes,text,heading,explanation=await self.describe(target)
        metrics=await target.evaluate("element=>({height:element.getBoundingClientRect().height,viewport:document.querySelector('.chat-feed').clientHeight})")
        step=max(200,int(metrics['viewport']-190))
        offsets=list(range(0,math.ceil(metrics['height']),step))
        hold=max(3,min(12,len(text.split())/len(offsets)/4.2))
        item=self.messages.setdefault(key,{'index':len(self.messages)+1,'actor':actor,'versions':[]})
        version={'text':text,'classes':classes,'start':self.now(),'pages':[],'annotation':{'heading':heading,'text':explanation}}
        for n,offset in enumerate(offsets):
            await target.evaluate("""(element,offset)=>{
             const feed=document.querySelector('.chat-feed');
             feed.scrollTop+=element.getBoundingClientRect().top-feed.getBoundingClientRect().top-100+offset;
            }""",offset)
            await bubble(self.page,heading,explanation,f'Live conversation · message {item["index"]} · part {n+1}/{len(offsets)}',target)
            await self.page.wait_for_timeout(150)
            name=f'{item["index"]:03d}-v{len(item["versions"])+1:02d}-{n+1:02d}.png'
            start=self.now()
            await self.page.screenshot(path=str(self.directory/name))
            await self.page.wait_for_timeout(hold*1000)
            version['pages'].append({'start':start,'end':self.now(),'screenshot':name})
        version['end']=self.now();item['versions'].append(version)
        self.last_read=(key,text)
        print(f'Live message {item["index"]}: {actor} ({len(offsets)} pages)',flush=True)

    async def before(self, kind, data):
        if kind.endswith('message_delta'):
            stream=data.get('stream_id') or kind+str(data.get('subagent_label',''))
            if self.stream_id and stream!=self.stream_id:await self.read()
            self.stream_id=stream
            await self.mode_to('reading')
        elif kind in STATIC or kind in {'subagent_started','subagent_completed','artifact_received','complete'}:
            await self.read()
            await self.mode_to('reading')

    async def after(self, kind, data):
        # Let React consume this genuine packet before inspecting its UI.
        await self.page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        if kind.endswith('message_delta'):
            target=await self.latest()
            if target is not None:
                if data.get('stream_id')=='final-summary':
                    self.final_key=(await self.describe(target))[0]
                await self.follow(target,'Live response streaming')
            return
        if kind in STATIC:
            await self.read()
        elif kind in {'subagent_completed','artifact_received','complete'}:
            await self.read();self.stream_id=None
        if kind in {'subagent_started','tool_observation','artifact_received'}:
            typing=self.page.locator('.typing-message').last
            if await typing.count():
                meta=await typing.locator('.message-meta').inner_text()
                heading=meta.replace('SPECIALIST AGENT · ','').replace('TEAM ASSISTANT · ','')
                detail='I’m reviewing the evidence. My response will appear here as it arrives.'
                if kind=='tool_observation':detail='I’m inspecting the records returned by '+str(data.get('tool','the authorized tool'))+'.'
                await typing.evaluate("element=>{const feed=document.querySelector('.chat-feed');feed.scrollTop=feed.scrollHeight;}")
                await bubble(self.page,heading,detail,'Waiting for live response',typing)
        if kind!='complete':await self.mode_to('loading')

    def finish(self):
        self.segments.append({'start':self.since,'end':self.now(),'mode':self.mode,'speed':6 if self.mode=='loading' else 1})


async def record(browser, args, directory):
    context=await browser.new_context(viewport=VIEWPORT,record_video_size=VIEWPORT,
        record_video_dir=str(directory),locale='en-US',timezone_id='Asia/Seoul')
    await context.add_init_script(STREAM)
    page=await context.new_page();video=page.video
    origin=time.monotonic();camera=Camera(page,directory,origin)
    await page.expose_function('filmBefore',camera.before)
    await page.expose_function('filmAfter',camera.after)
    log={'url':args.url,'request':REQUEST,'recording_mode':'Real SSE consumed live, with reading pauses between unchanged packets; loading accelerated 6x'}
    try:
        await page.goto(args.url,wait_until='networkidle',timeout=45000)
        await presentation(page)
        await page.evaluate("""()=>{
         document.querySelector('#conversation-guide .eyebrow').textContent='LIVE A2A CONVERSATION';
         document.querySelector('#conversation-guide .context').innerHTML='Real live responses, paced for reading.<br><br>Speech bubbles explain the exchange; original Agent messages remain on the left.';
         const speed=document.createElement('div');speed.id='live-speed';speed.textContent='LOADING · 6×';
         speed.style.cssText='visibility:hidden;margin-top:22px;color:#624980;font:700 17px Arial;padding:12px 16px;background:#f2e9ff;border-radius:15px;';
         document.querySelector('#conversation-guide').append(speed);
         document.querySelector('.chat-feed').style.setProperty('padding-bottom','70px','important');
        }""")
        log['start']=camera.now();camera.since=log['start']
        await bubble(page,'Operator → Orchestrator','Please review a CIP pump mechanical seal-kit purchase. Ask the Teams to verify the evidence.','Live A2A Harness demo')
        await page.locator('.composer textarea').fill(REQUEST)
        await page.wait_for_timeout(3000)
        await page.get_by_role('button',name='Run harness →',exact=True).click()
        await page.evaluate("()=>document.body.classList.add('full-walk')")
        print('Recording genuine live SSE, with reading pauses.',flush=True)
        deadline=time.monotonic()+900
        while time.monotonic()<deadline:
            state=await page.evaluate('()=>({done:window.__film.done,error:window.__film.error})')
            if state['error']:raise RuntimeError(state['error'])
            if state['done']:break
            await page.wait_for_timeout(500)
        else:raise TimeoutError('Live recording stalled beyond 15 minutes')
        await camera.read();camera.finish()
        result=await page.evaluate('()=>window.__film.latest.complete')
        if not result:raise RuntimeError('Missing genuine complete event')
        log['termination']=result.get('result',{}).get('termination',{})
        if log['termination'].get('state') not in {'completed','input_required'}:raise RuntimeError(str(log['termination']))
        log['final_summary']=result.get('result',{}).get('summary','')
        # Every message after the initial welcome must have been read in-stream.
        entries=page.locator('.chat-feed > :not(.typing-message)')
        log['message_count']=await entries.count()
        keys=await entries.evaluate_all("items=>items.slice(1).map(item=>item.dataset.filmId)")
        if any(not key or key not in camera.messages for key in keys):raise RuntimeError('An intermediate message was not filmed')
        log['coverage']=f'{len(keys)}/{len(keys)} conversation messages, plus welcome when visible'
        log['trace']=await page.evaluate('()=>window.__film.trace')
    except Exception as error:
        log['error']=str(error);await page.screenshot(path=str(directory/'failure.png'));raise
    finally:
        log['segments']=camera.segments;log['messages']=list(camera.messages.values())
        write_json(directory/'streaming.json',log)
        await context.close()
    return Path(await video.path()),log


def render(raw, output, log, directory):
    # Keep every frame in chronology. Only the waiting intervals change speed.
    output_time=0
    for segment in log['segments']:
        segment['output_start']=output_time
        output_time+=(segment['end']-segment['start'])/segment['speed']
        segment['output_end']=output_time
    # Map timestamps on a single continuous stream. A balanced expression avoids
    # hundreds of tiny concat segments and their frame-rounding errors.
    def expression(segments):
        if len(segments)==1:
            s=segments[0]
            return f"({s['output_start']:.6f}+(T-{s['start']:.6f})/{s['speed']})"
        middle=len(segments)//2
        return f"if(lt(T,{segments[middle]['start']:.6f}),{expression(segments[:middle])},{expression(segments[middle:])})"
    segments=log['segments']
    chain=f"[0:v]trim=start={segments[0]['start']:.6f}:end={segments[-1]['end']:.6f},setpts='{expression(segments)}/TB',fps=20,format=yuv420p[v]"
    extra_input=[]
    correction=log.get('annotation_correction')
    if correction:
        extra_input=['-loop','1','-framerate','25','-i',correction['image']]
        chain=chain.removesuffix('[v]')+'[base];'+f"[base][2:v]overlay=x=1500:y=0:enable='between(t,{correction['output_start']:.6f},{correction['output_end']:.6f})':shortest=1[v]"
    filters=directory/'filter.txt';filters.write_text(chain)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(raw),'-f','lavfi','-i',
        'anullsrc=channel_layout=stereo:sample_rate=48000',*extra_input,'-filter_complex',chain,
        '-map','[v]','-map','1:a:0','-c:v','libx264','-preset','slow','-tune','stillimage','-crf','27',
        '-c:a','aac','-shortest','-movflags','+faststart',str(output)],check=True)
    write_json(directory/'streaming.json',log)
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries',
        'format=duration,size:stream=codec_name,width,height','-of','json',str(output)],text=True))


async def main(args):
    if not 1<=args.attempts<=3:raise ValueError('Use 1–3 attempts')
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):raise RuntimeError('FFmpeg is required')
    run_dir=OUTPUT_DIR/'attempts'/datetime.now().strftime('%Y%m%d-%H%M%S-streaming')
    run_dir.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=not args.headed)
        try:
            for index in range(args.attempts):
                directory=run_dir/f'attempt-{index+1}';directory.mkdir()
                try:
                    raw,log=await record(browser,args,directory)
                except Exception as error:
                    print(f'Attempt {index+1}: {error}',flush=True)
                    continue
                output=OUTPUT_DIR/'live-a2a-harness-streaming.mp4'
                try:
                    media=render(raw,output,log,directory)
                except Exception as error:
                    print(f'Encoding failed; preserve {raw} and {directory / "streaming.json"}: {error}',flush=True)
                    return 1
                write_json(OUTPUT_DIR/'latest-streaming.json',{'video':str(output),'raw_video':str(raw),
                    'conversation_log':str(directory/'streaming.json'),'coverage':log['coverage'],'media':media})
                print(f'Created {output}; {media["format"]["duration"]} seconds; {log["coverage"]}',flush=True)
                return 0
        finally:await browser.close()
    return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default=LIVE_URL)
    parser.add_argument('--attempts',type=int,default=2)
    parser.add_argument('--headed',action='store_true')
    raise SystemExit(asyncio.run(main(parser.parse_args())))
