import { load, identifier } from "@/lib/data";
export type History={metric:string;start:string;end:string;unit:string|null;bucket_seconds:number;points:{at:string;mean:number;min:number;max:number;samples:number;evidence_id:string}[];status:string;truncated:boolean;missing_buckets:number;note:string};
export type Band={start:string;end:string|null;label:string};
export async function MetricChart({service,metric,bands=[],compact=false}:{service:string;metric:string;bands?:Band[];compact?:boolean}){
 const {items:h,error}=await load<History>(`/api/v1/metric-history?service=${identifier(service)}&metric=${identifier(metric)}&hours=24&buckets=288`);
 if(error||!h)return <div className="card"><h3>{metric}</h3><p role="alert">{error||"History unavailable"}</p></div>;
 const valid=h.points.filter(p=>Number.isFinite(p.mean)&&Number.isFinite(p.min)&&Number.isFinite(p.max)&&Number.isFinite(Date.parse(p.at))&&p.min<=p.mean&&p.mean<=p.max);
 const low=Math.min(0,...valid.map(p=>p.min)),high=Math.max(1,...valid.map(p=>p.max));
 const begin=Date.parse(h.start),finish=Date.parse(h.end),width=finish-begin;
 const x=(at:string)=>40+Math.max(0,Math.min(1,(Date.parse(at)-begin)/width))*720;
 const y=(v:number)=>150-(v-low)/(high-low)*125;
 const segments:typeof valid[]=[];
 for(const point of valid){const previous=segments[segments.length-1];if(!previous||Date.parse(point.at)-Date.parse(previous[previous.length-1].at)>h.bucket_seconds*1500)segments.push([point]);else previous.push(point);}
 return <section className="card" style={{minWidth:0}}><h3>{metric} / {h.unit||"unit unavailable"}</h3>{h.status!=="observed"?<p>{h.status==="no_data"?"No observed aggregate samples in this 24h window":`History state: ${h.status}`}</p>:<svg viewBox="0 0 800 185" role="img" aria-label={`${metric}, observed samples over 24 hours, gaps are missing data`} style={{width:"100%",height:compact?110:210}}>
 <line x1="40" y1="150" x2="760" y2="150" stroke="#35445a"/><line x1="40" y1="25" x2="40" y2="150" stroke="#35445a"/>
 {bands.filter(b=>Date.parse(b.start)<=finish&&(!b.end||Date.parse(b.end)>=begin)).map((b,n)=><rect key={n} x={x(b.start)} y="25" width={Math.max(2,x(b.end||h.end)-x(b.start))} height="125" fill="#ff4d6d" opacity=".14"><title>{b.label}: incident interval, not measured anomaly onset</title></rect>)}
 {segments.map((points,n)=><polyline key={n} points={points.map(p=>`${x(p.at)},${y(p.mean)}`).join(" ")} fill="none" stroke="#3dd6c6" strokeWidth="2"/>)}
 {valid.map(p=><circle key={p.at} cx={x(p.at)} cy={y(p.mean)} r="2.5" fill="#3dd6c6"><title>{p.at}: mean {p.mean}, min {p.min}, max {p.max}, {p.samples} samples, evidence {p.evidence_id}</title></circle>)}
 <text x="40" y="174" fill="#8aa0b8" fontSize="11">{h.start.slice(5,16)} UTC</text><text x="620" y="174" fill="#8aa0b8" fontSize="11">{h.end.slice(5,16)} UTC</text><text x="0" y="30" fill="#8aa0b8" fontSize="10">{high.toPrecision(3)}</text><text x="0" y="150" fill="#8aa0b8" fontSize="10">{low.toPrecision(3)}</text></svg>}
 <p className="muted">{h.missing_buckets} missing buckets. {h.truncated?"Truncated to latest 12000 source samples. ":""}Gaps are not zero; no interpolation.{bands.length>0?" Red bands are incident intervals, not independently measured anomaly windows.":""}</p>{!compact&&<details><summary>Bucket values and evidence IDs</summary><table className="table"><thead><tr><th>UTC bucket</th><th>Mean / min / max</th><th>Samples / evidence</th></tr></thead><tbody>{valid.map(p=><tr key={p.at}><td>{p.at}</td><td>{p.mean.toPrecision(4)} / {p.min.toPrecision(4)} / {p.max.toPrecision(4)}</td><td>{p.samples}<br/>{p.evidence_id}</td></tr>)}</tbody></table><p className="muted">{h.note}</p></details>}</section>;
}
