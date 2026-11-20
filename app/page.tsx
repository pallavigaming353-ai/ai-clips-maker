"use client";
import {useEffect,useState} from "react";
type Output={name:string;duration:number;start:number;aspect:string;video:string;srt:string};
type Job={id:string;status:string;outputs:Output[];error?:string};
const api=(process.env.NEXT_PUBLIC_API_BASE_URL||"http://localhost:8000").replace(/\/$/,"");
export default function Home(){
 const [file,setFile]=useState<File|null>(null);
 const [url,setUrl]=useState("");
 const [mode,setMode]=useState<"link"|"upload">("link");
 const [lengths,setLengths]=useState<number[]>([30,60]);
 const [job,setJob]=useState<Job|null>(null);
 const [busy,setBusy]=useState(false);
 const [error,setError]=useState("");
 useEffect(()=>{if(!job||["complete","failed"].includes(job.status))return;const id=setInterval(async()=>{try{const r=await fetch(api+"/api/jobs/"+job.id);if(r.ok)setJob(await r.json());}catch{setError("Cannot reach processing server.");}},3000);return()=>clearInterval(id)},[job?.id,job?.status]);
 async function submit(){if(mode==="upload"&&!file||mode==="link"&&!url.trim())return;setBusy(true);setError("");try{const data=new FormData();if(mode==="upload"&&file)data.append("file",file);if(mode==="link")data.append("url",url.trim());data.append("lengths",lengths.join(","));const r=await fetch(api+(mode==="link"?"/api/jobs/from-link":"/api/jobs"),{method:"POST",body:data});const body=await r.json();if(!r.ok)throw new Error(typeof body.detail==="string"?body.detail:"Upload failed");setJob(body);}catch(e){setError(e instanceof Error?e.message:"Upload failed")}finally{setBusy(false)}}
 return <main style={{maxWidth:1000,margin:"auto",padding:"44px 20px"}}>
 <p style={{color:"#6fd9ff",letterSpacing:3,fontWeight:700}}>AI CLIPS MAKER</p>
 <h1 style={{fontSize:"clamp(2.4rem,6vw,4.4rem)",marginBottom:8}}>Turn long videos into great clips.</h1>
 <p style={{color:"#a6b5d0"}}>Paste a trusted direct video link, or upload a file as a fallback. Export captioned clips in both formats.</p>
 <section style={{background:"#131d30",border:"1px solid #293955",borderRadius:20,padding:24,marginTop:28}}>
 <div style={{display:"flex",gap:12,marginBottom:18}}><button onClick={()=>setMode("link")} aria-pressed={mode==="link"}>Paste link</button><button onClick={()=>setMode("upload")} aria-pressed={mode==="upload"}>Upload file</button></div>
 {mode==="link"?<><label htmlFor="video-url">Direct MP4/MOV video URL</label><input id="video-url" type="url" placeholder="https://trusted-host.example/video.mp4" value={url} onChange={e=>setUrl(e.target.value)} style={{display:"block",width:"100%",padding:12,margin:"12px 0 8px",boxSizing:"border-box"}}/><p style={{color:"#a6b5d0"}}>Currently supports direct media URLs from hosts configured by the server owner. YouTube watch links are not supported yet.</p></>:<><label htmlFor="upload">Upload MP4 / MOV</label><input id="upload" type="file" accept="video/mp4,video/quicktime" onChange={e=>setFile(e.target.files?.[0]??null)} style={{display:"block",margin:"16px 0 24px",width:"100%"}}/></>}
 <p>Clip lengths</p><div style={{display:"flex",gap:12,flexWrap:"wrap"}}>{[30,60,1800].map(n=><label key={n} style={{padding:12,background:"#243650",borderRadius:10}}><input type="checkbox" checked={lengths.includes(n)} onChange={e=>setLengths(v=>e.target.checked?[...v,n]:v.filter(x=>x!==n))}/> {n===1800?"30 minutes":n+" seconds"}</label>)}</div><p style={{color:"#a6b5d0"}}>Hindi SRT + burned-in captions · 9:16 and 16:9</p>
 <button disabled={(mode==="upload"?!file:!url.trim())||lengths.length===0||busy||!!job&&!["complete","failed"].includes(job.status)} onClick={submit} style={{padding:"14px 22px",borderRadius:12,background:"#3d8aff",color:"white",border:0,cursor:"pointer"}}>{busy?"Submitting...":"Generate clips"}</button>
 {error&&<p role="alert" style={{color:"#ff9898"}}>{error}</p>}
 {job&&<p role="status">Job: {job.status}{job.error?" — "+job.error:""}</p>}
 </section>
 {job?.status==="complete"&&<section style={{marginTop:28}}><h2>Generated clips</h2><div style={{display:"grid",gridTemplateColumns:"repeat(auto-fit,minmax(260px,1fr))",gap:18}}>{job.outputs.map(o=><article key={o.name} style={{background:"#131d30",borderRadius:16,padding:16}}><h3>{o.duration}s · {o.aspect}</h3><video controls preload="metadata" src={api+o.video} style={{width:"100%",maxHeight:330,background:"black"}}/><p><a href={api+o.video} style={{color:"#7bd8ff"}}>Download MP4</a> · <a href={api+o.srt} style={{color:"#7bd8ff"}}>Download Hindi SRT</a></p></article>)}</div>{job.outputs.length===0&&<p>No clips were generated. Video may be shorter than the selected durations.</p>}</section>}
 <p style={{color:"#8998b0",fontSize:13,marginTop:28}}>Development preview: use only videos you own or are authorized to process. Backend must be running separately; uploads are not private-user authenticated yet.</p>
 </main>;
}
