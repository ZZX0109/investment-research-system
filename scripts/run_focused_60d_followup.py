#!/usr/bin/env python3
"""Focused follow-up: finish 60-session return tuning and test two earlier windows."""
from __future__ import annotations
import argparse, json, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import shutil
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/"src"))
from investment_research.training.resource_guard import ResourceMonitor, recommended_threads

def now(): return datetime.now(timezone.utc).isoformat()
def read(p, d):
    try: return json.loads(p.read_text())
    except (OSError,ValueError): return d
def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True); t=p.with_suffix(p.suffix+'.tmp'); t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n'); t.replace(p)
def trials():
    out=[]
    for lr in (0.0008,0.0010):
        for seed in (42,2026,3407):
            out.append({"id":f"return-w60-lr{lr:g}-s{seed}","task":"excess_return_240d","arch":"stockmixer","window":60,"hidden":128,"lr":lr,"seed":seed,"warm":True})
    for offset in (126,180):
        out.append({"id":f"return-w60-stability-end-{offset}","task":"excess_return_240d","arch":"stockmixer","window":60,"hidden":128,"lr":0.0006,"seed":3407,"warm":True,"offset":offset})
    return out
def report(root,t): return root/"cn/close_confirmed/cn_equity_core"/t["task"] / "panel"/t["arch"] / "variants"/t["id"]/"sequence_evaluation.json"
def cmd(a,t):
    x=[sys.executable,str(PROJECT/"scripts/run_panel_research_training.py"),"--sample-manifest-file",str(a.manifest),"--object-store",str(a.store),"--data-root",str(a.data),"--rebuild-index",str(a.rebuild),"--allow-research-only","--output-root",str(a.root),"--task",t["task"],"--architecture",t["arch"],"--variant",t["id"],"--cohort","cn_equity_core","--maximum-dates","1500","--window",str(t["window"]),"--batch-dates","64","--max-epochs","72","--hidden-size",str(t["hidden"]),"--learning-rate",str(t["lr"]),"--weight-decay","0.0001","--early-stop-patience","8","--seed",str(t["seed"]),"--training-run-id",f"{a.root.name}-{t['id']}"]
    if t["warm"]: x += ["--init-checkpoint",str(a.init),"--warm-start-mode","backbone","--warmup-epochs","6"]
    if t.get("offset"): x += ["--evaluation-end-offset",str(t["offset"]),"--holdout-sessions","126"]
    return x
def env():
    n=recommended_threads(); x=os.environ.copy(); x.update({"PYTHONPATH":str(PROJECT/"src"),"CUDA_VISIBLE_DEVICES":"0","INVESTMENT_RESEARCH_TORCH_DEVICE":"cuda","INVESTMENT_RESEARCH_GPU_MEMORY_FRACTION":"0.90","OMP_NUM_THREADS":str(n),"MKL_NUM_THREADS":str(n),"OPENBLAS_NUM_THREADS":str(n),"NUMEXPR_NUM_THREADS":str(n),"OMP_DYNAMIC":"FALSE","PYTHONUNBUFFERED":"1"}); return x
def main():
    p=argparse.ArgumentParser(); p.add_argument("--manifest",type=Path,required=True); p.add_argument("--store",type=Path,required=True); p.add_argument("--data",type=Path,required=True); p.add_argument("--rebuild",type=Path,required=True); p.add_argument("--root",type=Path,required=True); p.add_argument("--init",type=Path,required=True); p.add_argument("--hours",type=float,default=2.0); a=p.parse_args(); a.root.mkdir(parents=True,exist_ok=True); sp=a.root/"followup-status.json"; s=read(sp,{"status":"running","started_at":now(),"trials":[],"policy":{"gpu":"GPU0 only","epoch_resume":True,"sequential":True,"no_sequence_cache":True}}); deadline=time.time()+a.hours*3600
    for t in trials():
        r=report(a.root,t); old=next((z for z in s["trials"] if z["id"]==t["id"]),None)
        if r.is_file():
            item={**t,"status":"completed","report":str(r),"resumed":bool(old)}; s["trials"]=[z for z in s["trials"] if z["id"]!=t["id"]]+[item]; write(sp,s); continue
        if time.time()>=deadline or shutil.disk_usage(a.root).free < 12*1024**3: break
        item={**t,"status":"running","started_at":now()}; s["trials"]=[z for z in s["trials"] if z["id"]!=t["id"]]+[item]; write(sp,s); log=a.root/"logs"/f"{t['id']}.log"; log.parent.mkdir(parents=True,exist_ok=True)
        with log.open("a") as out:
            q=subprocess.Popen(cmd(a,t),cwd=PROJECT,env=env(),stdout=out,stderr=subprocess.STDOUT); m=ResourceMonitor(a.root/"monitoring"/f"{t['id']}.jsonl",interval_seconds=5,pid=q.pid); m.start()
            while q.poll() is None and time.time()<deadline: time.sleep(10)
            if q.poll() is None: q.terminate(); q.wait(timeout=60)
            m.stop(); item.update({"status":"completed" if q.returncode==0 else "checkpointed","exit_code":q.returncode,"finished_at":now(),"report":str(r)})
        s["trials"]=[z for z in s["trials"] if z["id"]!=t["id"]]+[item]; write(sp,s)
    s.update({"status":"completed_or_timeboxed","finished_at":now()}); write(sp,s)
if __name__=="__main__": main()
