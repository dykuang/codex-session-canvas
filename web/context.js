/* v0.3 Context Node Editor: graph topology, scoped selection, review, execution. */
(() => {
"use strict";
const app=window.codexCanvas;if(!app)return;
const make=(tag,cls="",label="")=>{const e=document.createElement(tag);e.className=cls;e.textContent=label;return e;};
const root=document.querySelector(".main"),bar=document.querySelector(".toolbar");
const toggle=make("button","tool-btn","◉ Context Graph");bar.insertBefore(toggle,bar.firstChild);
const overlay=make("section","ctx-overlay");overlay.hidden=true;root.append(overlay);
const controls=make("div","ctx-controls"),stage=make("div","ctx-stage"),world=make("div","ctx-world");
const svg=document.createElementNS("http://www.w3.org/2000/svg","svg"),cards=make("div","ctx-cards");
const editor=make("aside","ctx-editor"),status=make("div","ctx-status","Context Graph 仅在用户授权时读取历史正文。");
overlay.append(controls,stage,editor,status);svg.classList.add("ctx-lines");world.append(svg,cards);stage.append(world);
controls.append(make("strong","","CONTEXT NODE EDITOR"));
const picker=make("select","ctx-input");controls.append(picker);
const graphPicker=make("select","ctx-input");graphPicker.title="当前 Context Graph";controls.append(graphPicker);
const createGraphBtn=make("button","ctx-btn","+ Graph");controls.append(createGraphBtn);
const labels={session_source:"+ Source",selector:"+ Selector",summarize:"+ Summary",note:"+ Note",merge:"+ Merge",new_session:"+ New Session"};
const ports={session_source:[false,true],selector:[true,true],summarize:[true,true],note:[false,true],merge:[true,true],new_session:[true,false]};
const defaults={session_source:()=>({sessionId:picker.value}),selector:()=>({mode:"selected",segmentIds:[]}),summarize:()=>({text:"",approved:false}),note:()=>({text:""}),merge:()=>({budget:16000}),new_session:()=>({cwd:app.getData().sessions.find(s=>s.id===picker.value)?.cwd||app.getData().projects.flatMap(p=>p.folders||[])[0]||"",projectId:app.getData().sessions.find(s=>s.id===picker.value)?.project||"all",task:"",budget:16000})};
let graph={version:1,id:"main",projectId:"all",revision:0,nodes:[],edges:[]},open=false,dirty=false,selected=null,connecting=null,approval=null,packagePreview=null;
let pan={x:55,y:40,z:1},drag=null,dragWire=false;
const node=id=>graph.nodes.find(n=>n.id===id);
const inform=(s,error=false)=>{status.textContent=s;status.classList.toggle("ctx-error",error);};
const changed=()=>{dirty=true;approval=null;packagePreview=null;};
async function api(endpoint,body){if(!app.getData().live||app.getData().demo)throw Error("请使用本地 --serve 模式");
 const resp=await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json","X-Canvas-CSRF":app.getData().csrfToken},body:JSON.stringify(body)});
 const result=await resp.json();if(!resp.ok)throw Error(result.error||resp.status);return result;}
function updatePicker(){let old=picker.value;picker.replaceChildren();for(const s of app.getData().sessions){const o=make("option","",s.name+" · "+s.id.slice(0,8));o.value=s.id;picker.append(o);}if([...picker.options].some(x=>x.value===old))picker.value=old;}
async function refreshGraphList(){if(!app.getData().live)return;const resp=await fetch("/api/context/graphs");const result=await resp.json();if(!resp.ok)throw Error(result.error);const old=graph.id;graphPicker.replaceChildren();
 const ids=new Set(["main",...result.graphs.map(g=>g.id)]);for(const id of ids){const o=make("option","",id);o.value=id;graphPicker.append(o);}
 if(ids.has(old))graphPicker.value=old;}
async function load(id){if(!app.getData().live)return;try{const gid=id||graph.id||"main";
 const resp=await fetch("/api/context/graph?id="+encodeURIComponent(gid));const result=await resp.json();if(!resp.ok)throw Error(result.error);
 graph=result.graph;selected=null;dirty=false;approval=null;await refreshGraphList();render();}catch(e){inform("加载失败："+e.message,true);}}
graphPicker.onchange=()=>{if(dirty&&!confirm("未保存的图修改将丢失，继续切换？")){graphPicker.value=graph.id;return;}load(graphPicker.value);};
createGraphBtn.onclick=()=>{if(dirty)return inform("请先保存当前图",true);const id=prompt("新 Context Graph ID（字母、数字、-、_、.）");if(!id)return;
 if(!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$/.test(id))return inform("Graph ID 不合法",true);
 graph={version:1,id,projectId:"all",revision:0,nodes:[],edges:[]};selected=null;changed();render();inform("新图尚未保存，点击保存");};
function show(next){if(next===open)return;if(!next&&dirty&&!confirm("尚有未保存的 Context Graph 修改，确定离开？"))return;
 if(next){const p=document.getElementById("project-graph");if(p&&!p.hidden){document.getElementById("project-graph-toggle").click();if(!p.hidden)return;}}
 open=next;overlay.hidden=!next;document.getElementById("board").style.display=next?"none":"";
 document.querySelector(".zoom").style.display=next?"none":"";document.getElementById("notice").style.display=next?"none":"";
 if(next){updatePicker();load();render();}}
toggle.onclick=()=>show(!open);
const projectBtn=document.getElementById("project-graph-toggle");if(projectBtn)projectBtn.addEventListener("click",()=>{if(open)show(false);});
for(const [kind,label] of Object.entries(labels)){const btn=make("button","ctx-btn",label);controls.append(btn);
 btn.onclick=()=>{if(!app.getData().live)return inform("静态模式不可编辑",true);if(kind==="session_source"&&!picker.value)return inform("当前没有可用的本地 Session",true);
 const id="n"+crypto.randomUUID().replaceAll("-","").slice(0,12);
 const count=graph.nodes.filter(n=>n.type===kind).length;
 const xy={session_source:[70,75+count*145],selector:[350,75+count*145],
 summarize:[630,75+count*145],note:[350,490+count*145],
 merge:[890,150+count*145],new_session:[1170,150+count*145]}[kind];
 graph.nodes.push({id,type:kind,x:xy[0],y:xy[1],config:defaults[kind]()});changed();selected=id;render();};}
const saveBtn=make("button","ctx-btn primary","保存"),previewBtn=make("button","ctx-btn","预览"),runBtn=make("button","ctx-btn","创建 Session"),historyBtn=make("button","ctx-btn","运行记录"),backBtn=make("button","ctx-btn","返回");
controls.append(saveBtn,previewBtn,runBtn,historyBtn,backBtn);
historyBtn.onclick=async()=>{try{const r=await fetch("/api/context/runs");const result=await r.json();if(!r.ok)throw Error(result.error);
 editor.replaceChildren(make("h3","","CONTEXT RUN HISTORY"));for(const run of result.runs){const row=make("div","ctx-edge");
 row.append(make("span","",run.status+" · "+(run.threadId||"pending")+" · "+run.graphId));
 const btn=make("button","ctx-btn","查看");btn.onclick=()=>showRunActions(run);row.append(btn);editor.append(row);}
 if(!result.runs.length)editor.append(make("p","","没有历史执行记录"));}catch(e){inform("记录读取失败："+e.message,true);}};backBtn.onclick=()=>show(false);
async function save(){try{const r=await api("/api/context/graph",{graph});graph=r.graph;dirty=false;approval=null;await refreshGraphList();inform("已保存 Context Graph · revision "+graph.revision);return true;}catch(e){inform("保存失败："+e.message,true);return false;}}
saveBtn.onclick=save;
previewBtn.onclick=async()=>{if(dirty&&!(await save()))return;if(!confirm("明确读取已连接的历史 Session 内容，用于本次预览？"))return;
 try{const r=await api("/api/context/preview",{graphId:graph.id,consent:true});approval=r.approvalToken;packagePreview=r.package;
 editor.replaceChildren(make("h3","","CONTEXT PACKAGE · REVIEW"),make("p","","来源："+r.package.sources.length+" · 估算 "+r.package.estimatedTokens+" tokens"),
 make("p","ctx-small","SHA256: "+r.package.promptHash));
 const area=make("textarea","ctx-input");area.rows=18;area.value=r.package.prompt;editor.append(area);
 const redact=make("button","ctx-btn","应用脱敏修改（仅当前预览）");
 redact.onclick=async()=>{try{const updated=await api("/api/context/redact",{approvalToken:approval,editedPrompt:area.value});
 packagePreview=updated.package;approval=updated.approvalToken;
 inform("脱敏修改已应用 · SHA256 "+packagePreview.promptHash+"，本次预览需重新确认创建");
 }catch(e){inform("脱敏修改未通过校验："+e.message,true);}};
 editor.append(redact);
 const copy=make("button","ctx-btn","复制预览内容（手动创建备用方案）");
 copy.onclick=async()=>{try{await navigator.clipboard.writeText(area.value);inform("已复制当前预览内容；可手动粘贴到新 Codex Session");}
 catch{area.focus();area.select();inform("请按 Ctrl+C 复制选中的内容");}};
 editor.append(copy);
 editor.append(make("p","ctx-small","请检查敏感内容。修改源节点后重新预览；执行之前还需再次确认。"));
 inform("预览已生成，尚未创建 Codex Session。");
 }catch(e){inform("预览失败："+e.message,true);}};
runBtn.onclick=async()=>{if(!approval||!packagePreview)return inform("请先预览并确认 Context Package",true);
 if(!confirm("确认将预览内容发送给 Codex，在 "+packagePreview.cwd+" 新建真实 Session？"))return;
 try{const r=await api("/api/context/execute",{approvalToken:approval,promptHash:packagePreview.promptHash,approved:true});approval=null;
 inform("正在创建 Codex Session · run "+r.run.id);watch(r.run.id);
 }catch(e){approval=null;inform("创建失败："+e.message,true);}};
function showRunActions(run){
 if(!run.threadId)return;
 const actions=make("div","ctx-run-actions");
 actions.append(make("strong","","Codex Session · "+run.threadId));
 const openBtn=make("button","ctx-btn","↗ 打开 Codex Desktop");
 openBtn.onclick=()=>{if(!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(run.threadId))
 return inform("此运行时的 threadId 不是桌面深链支持的 UUID",true);
 window.location.href="codex://threads/"+run.threadId;};
 const copyBtn=make("button","ctx-btn","复制 CLI 恢复命令");
 copyBtn.onclick=async()=>{
 const cwd=run.cwd||packagePreview?.cwd||"";
 const win=navigator.platform.toLowerCase().includes("win");
 const command=win?"Set-Location -LiteralPath '"+cwd.replaceAll("'","''")+"'; codex resume "+run.threadId:
 "cd '"+cwd.replaceAll("'","'\\''")+"' && codex resume "+run.threadId;
 try{await navigator.clipboard.writeText(command);inform("已复制 CLI 恢复命令");}catch{inform("剪贴板不可用，请手动使用 codex resume "+run.threadId,true);}};
 actions.append(openBtn,copyBtn);editor.replaceChildren(make("h3","","SESSION CREATED / STATUS"),actions);
}
async function watch(id){for(let i=0;i<90&&open;i++){await new Promise(r=>setTimeout(r,2000));try{const r=await fetch("/api/context/run?id="+encodeURIComponent(id));const result=await r.json();if(!r.ok)throw Error(result.error);
 const run=result.run;inform(run.status+" · "+(run.threadId||"尚未返回 Session ID")+(run.error?" · "+run.error:""),run.status==="error");if(run.threadId)showRunActions(run);if(["error","completed"].includes(run.status))return;
 }catch(e){inform("状态查询失败："+e.message,true);return;}}inform("状态轮询已停止，请在 Codex 检查实际结果，勿直接重复创建",true);}
function wire(from,to){const a=node(from),b=node(to);if(!a||!b||from===to||!ports[a.type][1]||!ports[b.type][0])throw Error("无效端口");
 if((a.type==="session_source")!==(b.type==="selector"))throw Error("Session Source 只能连接 Selector；Selector 只能接收 Session Source");
 if(!["merge","new_session"].includes(b.type)&&graph.edges.some(e=>e.to===to))throw Error("该输入端口只允许一条连线");
 if(graph.edges.some(e=>e.from===from&&e.to===to))return;
 const edges=[...graph.edges,{from,to,out:"out",in:b.type==="selector"?"source":"in"}];const next=new Map(graph.nodes.map(n=>[n.id,[]]));
 for(const e of edges)next.get(e.from).push(e.to);
 const visiting=new Set(),done=new Set();
 function visit(k){if(visiting.has(k))throw Error("检测到循环依赖");if(done.has(k))return;visiting.add(k);for(const child of next.get(k))visit(child);visiting.delete(k);done.add(k);}
 for(const n of graph.nodes)visit(n.id);graph.edges=edges;changed();}
function edgesDraw(){svg.replaceChildren();for(const e of graph.edges){const a=node(e.from),b=node(e.to);if(!a||!b)continue;const p=document.createElementNS("http://www.w3.org/2000/svg","path");
 p.setAttribute("d","M"+(a.x+206)+" "+(a.y+45)+" C"+(a.x+280)+" "+(a.y+45)+","+(b.x-60)+" "+(b.y+45)+","+b.x+" "+(b.y+45));p.setAttribute("class","ctx-wire");svg.append(p);}}
function render(){cards.replaceChildren();let w=1100,h=750;for(const n of graph.nodes){w=Math.max(w,n.x+340);h=Math.max(h,n.y+170);}
 world.style.width=w+"px";world.style.height=h+"px";svg.setAttribute("width",w);svg.setAttribute("height",h);
 for(const n of graph.nodes){const card=make("div","ctx-node"+(selected===n.id?" selected":""),"");card.dataset.kind=n.type;card.style.left=n.x+"px";card.style.top=n.y+"px";
 card.append(make("div","ctx-head",labels[n.type].slice(2)));
 if(ports[n.type][0]){const inp=make("button","ctx-port ctx-in","●");inp.title="输入端口";inp.dataset.nodeId=n.id;card.append(inp);inp.onclick=e=>{e.stopPropagation();if(!connecting)return inform("请先点击源节点的输出端口");
 try{wire(connecting,n.id);inform("已连接节点");}catch(err){inform(err.message,true);}connecting=null;render();};}
 if(ports[n.type][1]){const out=make("button","ctx-port ctx-out","●");out.title="输出端口";card.append(out);out.onpointerdown=e=>{e.stopPropagation();connecting=n.id;dragWire=true;inform("拖动到目标输入端口，或点击另一个输入端口");};out.onclick=e=>{e.stopPropagation();connecting=n.id;inform("请选择目标节点输入端口");};}
 const summary=n.type==="session_source"?app.getData().sessions.find(s=>s.id===n.config.sessionId)?.name||n.config.sessionId:n.type==="selector"?(n.config.segmentIds||[]).length+" segments":n.config.text||n.config.task||"配置节点";
 card.append(make("div","ctx-body",String(summary||"").slice(0,100)));
 card.onclick=()=>{selected=n.id;render();};
 let down=null,move=false;card.onpointerdown=e=>{if(e.target.closest("button"))return;down={x:e.clientX,y:e.clientY,nx:n.x,ny:n.y};move=false;card.setPointerCapture(e.pointerId);e.stopPropagation();};
 card.onpointermove=e=>{if(!down)return;const dx=(e.clientX-down.x)/pan.z,dy=(e.clientY-down.y)/pan.z;if(Math.abs(dx)+Math.abs(dy)>3)move=true;if(move){n.x=down.nx+dx;n.y=down.ny+dy;card.style.left=n.x+"px";card.style.top=n.y+"px";edgesDraw();}};
 card.onpointerup=e=>{if(down&&move)changed();down=null;e.stopPropagation();};cards.append(card);}
 edgesDraw();inspect();}
function field(label,elem){editor.append(make("label","",label),elem);return elem;}
function change(n,key,value){n.config[key]=value;changed();render();}
function inspect(){editor.replaceChildren();const n=node(selected);if(!n){editor.append(make("h3","","CONTEXT INSPECTOR"),make("p","","选择节点设置输入、输出及文本。"));return;}
 editor.append(make("h3","",labels[n.type].slice(2)),make("p","ctx-small",n.id));
 function txt(key,label,rows=1){const inp=make(rows>1?"textarea":"input","ctx-input");inp.value=n.config[key]||"";if(rows>1)inp.rows=rows;field(label,inp);inp.onchange=()=>change(n,key,inp.value);}
 if(n.type==="session_source"){const sel=make("select","ctx-input");for(const s of app.getData().sessions){const o=make("option","",s.name+" · "+s.id.slice(0,8));o.value=s.id;sel.append(o);}sel.value=n.config.sessionId;field("Session ID",sel);sel.onchange=()=>change(n,"sessionId",sel.value);}
 if(n.type==="selector"){const mode=make("select","ctx-input");for(const v of ["selected","all"]){const o=make("option","",v==="all"?"全部片段":"选定片段");o.value=v;mode.append(o);}mode.value=n.config.mode||"selected";field("选取范围",mode);mode.onchange=()=>change(n,"mode",mode.value);
 const read=make("button","ctx-btn","明确授权读取此 Session");editor.append(read);
 read.onclick=async()=>{const e=graph.edges.find(e=>e.to===n.id),src=node(e?.from);if(!src||src.type!=="session_source")return inform("先连接 Session Source",true);
 if(!confirm("读取指定 Session 的用户/助手内容供你选择？"))return;
 try{const r=await api("/api/context/source",{sessionId:src.config.sessionId,consent:true});const group=make("div","ctx-segments");editor.append(group);
 for(const seg of r.segments){const row=make("label","ctx-segment");const box=make("input");box.type="checkbox";box.checked=(n.config.segmentIds||[]).includes(seg.id);
 box.onchange=()=>{const ids=new Set(n.config.segmentIds||[]);if(box.checked)ids.add(seg.id);else ids.delete(seg.id);n.config.segmentIds=[...ids];n.config.mode="selected";changed();};
 row.append(box,make("span","",seg.role+" "+seg.id+" · "+seg.text.slice(0,160)));group.append(row);}inform("已读取 "+r.segments.length+" 个片段（并未保存正文）");}catch(e){inform("读取失败："+e.message,true);}};}
 if(n.type==="note")txt("text","人工 Context Note",6);
 if(n.type==="summarize"){txt("text","人工审核后的 Summary",6);const box=make("input");box.type="checkbox";box.checked=n.config.approved===true;const row=make("label","ctx-check","已审核摘要");row.prepend(box);editor.append(row);box.onchange=()=>change(n,"approved",box.checked);}
 if(n.type==="merge"||n.type==="new_session"){const b=make("input","ctx-input");b.type="number";b.min=200;b.max=200000;b.value=n.config.budget||16000;field("预算（估算 Tokens）",b);b.onchange=()=>change(n,"budget",Number(b.value));}
 if(n.type==="new_session"){const folders=new Set();for(const p of app.getData().projects)for(const f of p.folders||[])if(f)folders.add(f);for(const s of app.getData().sessions)if(s.cwd)folders.add(s.cwd);
 const cwd=make("select","ctx-input");for(const f of [...folders].sort()){const o=make("option","",f);o.value=f;cwd.append(o);}if(n.config.cwd&&!folders.has(n.config.cwd)){const o=make("option","",n.config.cwd);o.value=n.config.cwd;cwd.append(o);}
 cwd.value=n.config.cwd||"";field("目标工作文件夹",cwd);cwd.onchange=()=>change(n,"cwd",cwd.value);txt("task","新 Session 初始任务",7);}
 editor.append(make("h4","","连线"));
 for(const e of graph.edges.filter(e=>e.from===n.id||e.to===n.id)){const row=make("div","ctx-edge",e.from+" → "+e.to);const del=make("button","ctx-btn","×");del.onclick=()=>{graph.edges=graph.edges.filter(x=>x!==e);changed();render();};row.append(del);editor.append(row);}
 const del=make("button","ctx-btn danger","删除节点");editor.append(del);del.onclick=()=>{if(!confirm("删除此节点及连线？"))return;graph.nodes=graph.nodes.filter(x=>x!==n);graph.edges=graph.edges.filter(e=>e.from!==n.id&&e.to!==n.id);selected=null;changed();render();};}
stage.addEventListener("pointerdown",e=>{if(e.target.closest(".ctx-node"))return;drag={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y};stage.setPointerCapture(e.pointerId);});
stage.addEventListener("pointermove",e=>{if(drag){pan.x=drag.px+e.clientX-drag.x;pan.y=drag.py+e.clientY-drag.y;applyPan();}
 if(dragWire&&connecting){edgesDraw();const n=node(connecting);if(!n)return;const r=stage.getBoundingClientRect();
 const px=(e.clientX-r.left-pan.x)/pan.z,py=(e.clientY-r.top-pan.y)/pan.z;
 const p=document.createElementNS("http://www.w3.org/2000/svg","path");
 p.setAttribute("d","M"+(n.x+206)+" "+(n.y+45)+" C"+(n.x+290)+" "+(n.y+45)+","+(px-50)+" "+py+","+px+" "+py);
 p.setAttribute("class","ctx-wire ctx-wire-preview");svg.append(p);}
});
stage.addEventListener("pointerup",e=>{drag=null;if(!dragWire)return;dragWire=false;
 const target=document.elementFromPoint(e.clientX,e.clientY)?.closest(".ctx-in");
 if(target&&connecting){const from=connecting;connecting=null;try{wire(from,target.dataset.nodeId);inform("已连接节点");}catch(err){inform(err.message,true);}render();}
 else{edgesDraw();inform("未选中输入端口，可点击目标输入端口完成连线");}});
stage.addEventListener("wheel",e=>{e.preventDefault();const r=stage.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top;const z=Math.min(2.2,Math.max(.25,pan.z*(e.deltaY<0?1.12:.89)));pan.x=x-(x-pan.x)*z/pan.z;pan.y=y-(y-pan.y)*z/pan.z;pan.z=z;applyPan();},{passive:false});
const applyPan=()=>world.style.transform="translate("+pan.x+"px,"+pan.y+"px) scale("+pan.z+")";
window.addEventListener("keydown",e=>{if(e.key==="Escape")connecting=null;});
applyPan();render();
})();
