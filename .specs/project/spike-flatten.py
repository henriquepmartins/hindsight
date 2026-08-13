import json, os, hashlib, collections
src=json.load(open('praw/drug-event-0001-of-0034.json'))['results']
fr=open('X_report.ndjson','w'); fd=open('X_drug.ndjson','w'); fx=open('X_reaction.ndjson','w')
dim={}
kof=lambda o: hashlib.sha1(json.dumps(o,sort_keys=True).encode()).hexdigest()[:16]
for r in src:
    rid=r.get('safetyreportid'); p=r.get('patient') or {}
    row={k:v for k,v in r.items() if k!='patient'}
    row.update({'pt_'+k:v for k,v in p.items() if k not in ('drug','reaction')})  # prefixed => unambiguous
    fr.write(json.dumps(row)+'\n')
    for i,d in enumerate(p.get('drug') or []):
        o=d.get('openfda'); k=kof(o) if o is not None else None
        if k and k not in dim: dim[k]={'openfda_key':k,**o}
        fd.write(json.dumps({'safetyreportid':rid,'seq':i,'openfda_key':k,
                             **{a:b for a,b in d.items() if a!='openfda'}})+'\n')
    for i,x in enumerate(p.get('reaction') or []):
        fx.write(json.dumps({'safetyreportid':rid,'seq':i,**x})+'\n')
open('X_drugdim.ndjson','w').writelines(json.dumps(v)+'\n' for v in dim.values())
for f in (fr,fd,fx): f.close()

# ---- ROUND TRIP ----
rep=[json.loads(l) for l in open('X_report.ndjson')]
dimr={d['openfda_key']:{k:v for k,v in d.items() if k!='openfda_key'} for d in (json.loads(l) for l in open('X_drugdim.ndjson'))}
dg=collections.defaultdict(dict); rx=collections.defaultdict(dict)
for l in open('X_drug.ndjson'):
    d=json.loads(l); dg[d['safetyreportid']][d['seq']]=d
for l in open('X_reaction.ndjson'):
    x=json.loads(l); rx[x['safetyreportid']][x['seq']]=x
def sn(o):
    if isinstance(o,dict): return {k:sn(v) for k,v in o.items() if v is not None}
    if isinstance(o,list): return [sn(v) for v in o]
    return o
mm=0; diffs=collections.Counter()
for i,orig in enumerate(src):
    r=dict(rep[i]); rid=r['safetyreportid']
    pat={k[3:]:r.pop(k) for k in list(r) if k.startswith('pt_')}
    rb=dict(r)
    dl=[]
    for s in sorted(dg[rid]):
        d=dict(dg[rid][s]); d.pop('safetyreportid'); d.pop('seq'); k=d.pop('openfda_key')
        if k is not None: d["openfda"]=dimr[k]
        dl.append(d)
    if dl: pat['drug']=dl
    xl=[]
    for s in sorted(rx[rid]):
        x=dict(rx[rid][s]); x.pop('safetyreportid'); x.pop('seq'); xl.append(x)
    if xl: pat['reaction']=xl
    if pat: rb['patient']=pat
    a=sn(orig); b=sn(rb)
    if json.dumps(a,sort_keys=True)!=json.dumps(b,sort_keys=True):
        mm+=1; diffs.update(set(a)^set(b) or ['<values differ>'])
print(f'reports compared: {len(src):,}')
print(f'byte-identical:   {len(src)-mm:,}')
print(f'MISMATCHES:       {mm}')
if diffs: print('differing keys:', dict(diffs))
tot=sum(os.path.getsize(f'X_{t}.ndjson') for t in ['report','drug','reaction','drugdim'])/1048576
print(f'ndjson total: {tot:.1f} MB')
