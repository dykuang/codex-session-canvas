(() => {
"use strict";
let data = JSON.parse(document.getElementById('initial-data').textContent);
let focus = data.focus || 'all';
let query = '';
let selected = null;
let linkingChild = null;
let manual = readStored('manual', {});
for (const id of Object.keys(manual)) if (typeof manual[id] === 'string') manual[id] = [{from: manual[id], type: 'manual'}];
let linkingType = 'manual';
let layoutPositions = readStored('positions', {});
const els = Object.fromEntries(['board','viewport','edges','edge-layer','nodes','project-list','project-total','current-project','search','refresh','fit','reset','stats','status','notice','inspector','detail-title','detail-meta','open-desktop','copy-resume','link-parent','unlink-parent','zoom-value'].map(k => [k, document.getElementById(k)]));
const camera = { x: 20, y: 20, scale: 1 };
let worldW = 850, worldH = 550, visible = [], edges = [], positions = {}, laneHeaders = [];
const NODE_W = 240, NODE_H = 104;
const ID = x => String(x || '');
function readStored(key, fallback){try { return JSON.parse(localStorage.getItem('codex-canvas:v1:'+key) || 'null') || fallback; } catch { return fallback; }}
function saveStored(key, val){try {localStorage.setItem('codex-canvas:v1:'+key, JSON.stringify(val));} catch {}}
function byId(id){ return data.sessions.find(s => s.id === id); }
function text(tag, cls, content){const e = document.createElement(tag);if(cls)e.className=cls;e.textContent=String(content ?? '');return e;}
function briefDate(timestamp){const t = Date.parse(timestamp);return Number.isFinite(t) ? new Date(t).toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'}) : '--';}
function showToast(message){ const e = text('div','toast',message);document.querySelector('.main').appendChild(e);setTimeout(()=>e.remove(),2400);}
function projectName(p){return data.projects.find(x=>x.id===p)?.name || p || '未知项目';}
function selectProject(id){focus=id;selected=null;linkingChild=null;els.inspector.classList.remove('visible');drawSidebar();render();fit();}
function drawSidebar(){const c=els['project-list'];c.replaceChildren();els['project-total'].textContent=data.projects.length;
 const entries=[{id:'all',name:'全部项目',count:data.sessions.length},...data.projects];
 for(const p of entries){const btn=text('button','project'+(p.id===focus?' active':''),'');btn.title=p.id==='all'?'All Projects':p.id;const icon=text('span','p-icon',p.id==='all'?'◈':'⌁');const name=text('span','p-name',p.name);const count=text('span','p-count',p.count);btn.append(icon,name,count);btn.addEventListener('click',()=>selectProject(p.id));c.appendChild(btn);}
 els['current-project'].textContent=focus==='all'?'全部项目':focus.startsWith('session:')?'当前会话':projectName(focus);
}
function parentEdges(sessions){const ids=new Set(sessions.map(s=>s.id));const output=[];
 for(const s of sessions){
  const p=s.parentThread && ids.has(s.parentThread)?s.parentThread:null;
  const f=s.forkedFrom && ids.has(s.forkedFrom)?s.forkedFrom:null;
  if(p)output.push({from:p,to:s.id,type:'parent',primary:true});
  if(f)output.push({from:f,to:s.id,type:'fork',primary:!p});
  let hasPrimary=!!(p||f);
  for(const edge of (data.cloudRelationships||[])) if(edge.to===s.id && ids.has(edge.from) && edge.from!==s.id){
   output.push({from:edge.from,to:s.id,type:edge.type,primary:!hasPrimary,evidence:edge.evidence});hasPrimary=true;
  }
  for(const m of (manual[s.id] || [])) if(ids.has(m.from) && m.from!==s.id){output.push({from:m.from,to:s.id,type:m.type,primary:!hasPrimary,evidence:'manual'});hasPrimary=true;}
 }
 return output;
}
function matches(s){return !query || [s.name,s.id,s.project,s.cwd].some(v=>String(v||'').toLocaleLowerCase().includes(query));}
function computeVisible(){let sessions=data.sessions.filter(s=>focus==='all'||s.project===focus||focus==='session:'+s.id);
 if(!query)return sessions;
 const included=new Set(sessions.filter(matches).map(s=>s.id));const map=new Map(sessions.map(s=>[s.id,s]));
 for(const id of [...included]){let s=map.get(id);const path=new Set([id]);while(s){const parent=s.parentThread || s.forkedFrom || manual[s.id]?.[0]?.from;if(!parent || path.has(parent) || !map.has(parent))break;path.add(parent);included.add(parent);s=map.get(parent);}}
 return sessions.filter(s=>included.has(s.id));
}
function calculateLayout(){visible=computeVisible();edges=parentEdges(visible);positions={};laneHeaders=[];
 const groups=new Map();for(const s of visible){if(!groups.has(s.project))groups.set(s.project,[]);groups.get(s.project).push(s);}
 const ordered=[...groups.entries()].sort(([a],[b])=>{const ai=data.projects.findIndex(p=>p.id===a),bi=data.projects.findIndex(p=>p.id===b);return ai-bi;});
 let top=55;let maxX=900;
 for(const [project,items] of ordered){const offset=top;const projectEdges=edges.filter(e=>items.some(s=>s.id===e.from) && items.some(s=>s.id===e.to) && e.primary);
  const parent=new Map(projectEdges.map(e=>[e.to,e.from]));const children=new Map();items.forEach(s=>children.set(s.id,[]));
  for(const [child,p] of parent){if(children.has(p))children.get(p).push(child);}
  const roots=items.filter(s=>!parent.has(s.id));const sorted=arr=>arr.sort((a,b)=>(byId(b)?.updatedUnix||0)-(byId(a)?.updatedUnix||0));
  sorted(roots);for(const c of children.values())sorted(c);
  let leaf=0;const placed=new Set();
  function lay(id,depth,trail){if(placed.has(id)||trail.has(id))return null;const stack=new Set(trail);stack.add(id);placed.add(id);const descendants=children.get(id)||[];
   const ys=[];for(const child of descendants){const y=lay(child,depth+1,stack);if(y!==null)ys.push(y);}
   let cy;if(ys.length){cy=(Math.min(...ys)+Math.max(...ys))/2;}else{cy=offset+68+leaf*137;leaf++;}
   const old=layoutPositions[id];const x=old && Number.isFinite(old.x)?old.x:65+depth*315;
   const y=old && Number.isFinite(old.y)?old.y:cy;
   positions[id]={x,y};maxX=Math.max(maxX,x+NODE_W+90);return cy;
  }
  for(const s of roots)lay(s.id,0,new Set());
  for(const s of items)if(!placed.has(s.id))lay(s.id,0,new Set());
  const coords=items.map(s=>positions[s.id]).filter(Boolean);const maxY=coords.length?Math.max(...coords.map(x=>x.y)):offset;
  laneHeaders.push({name:projectName(project),count:items.length,y:offset-15});
  top=Math.max(offset+150,maxY+NODE_H+120);
 }
 worldH=Math.max(520,top+80);worldW=maxX;
}
function makeNode(s){const pos=positions[s.id];let kind='ROOT';let type='';
 if(manual[s.id]?.length && visible.some(v=>v.id===manual[s.id][0].from)){kind='MANUAL LINK';type='manual';}
 else if(s.parentThread && visible.some(v=>v.id===s.parentThread)){kind='SIDE / CHILD';type='side';}
 else if(s.forkedFrom && visible.some(v=>v.id===s.forkedFrom)){kind='FORK';}
 if(s.source==='chatgpt'){kind='CHATGPT · CLOUD';type='cloud';}
 const el=text('article','node '+type+(s.archived?' archived':'')+(selected===s.id?' selected':'')+(query&&matches(s)?' match':''),'');el.style.left=pos.x+'px';el.style.top=pos.y+'px';el.dataset.id=s.id;
 const top=text('div','node-top','');top.append(text('span','node-dot',''),text('span','node-kind',kind),text('span','node-menu','•••'));
 const bottom=text('div','node-bottom','');bottom.append(text('span','',briefDate(s.updated)));
 bottom.append(text('em','',s.id.slice(0,16)));
 if(s.source==='chatgpt')bottom.append(text('em','cloud-label','云端快照'));
 if(s.archived)bottom.append(text('em','archive','已归档'));
 else if(s.archivedKnown===false)bottom.append(text('em','','归档未知'));
 el.append(top,text('div','node-title',s.name),bottom);
 let down=null,moved=false;
 el.addEventListener('pointerdown',ev=>{if(ev.button!==0)return;down={x:ev.clientX,y:ev.clientY,pos:{...positions[s.id]}};moved=false;el.setPointerCapture(ev.pointerId);ev.stopPropagation();});
 el.addEventListener('pointermove',ev=>{if(!down)return;const dx=ev.clientX-down.x,dy=ev.clientY-down.y;if(Math.abs(dx)+Math.abs(dy)>5)moved=true;if(moved){positions[s.id]={x:down.pos.x+dx/camera.scale,y:down.pos.y+dy/camera.scale};el.style.left=positions[s.id].x+'px';el.style.top=positions[s.id].y+'px';drawEdges();}});
 el.addEventListener('pointerup',ev=>{if(!down)return;down=null;ev.stopPropagation();if(moved){layoutPositions[s.id]={...positions[s.id]};saveStored('positions',layoutPositions);return;}if(linkingChild){if(linkingChild===s.id){showToast('不能将节点关联到自身');return;}manual[linkingChild] ||= []; if(!manual[linkingChild].some(m=>m.from===s.id && m.type===linkingType)) manual[linkingChild].push({from:s.id,type:linkingType});saveStored('manual',manual);linkingChild=null;els.board.classList.remove('linking');showToast('已保存手动关系');render();return;}selectSession(s.id);});
 el.addEventListener('dblclick',ev=>{ev.stopPropagation();if(data.demo){showToast('演示数据不对应真实 Codex 会话');return;}if(s.source==='chatgpt'){selectSession(s.id);showToast('ChatGPT 快照不提供已验证的深度链接');return;}openDesktop(s.id);});
 return el;
}
function drawEdges(){const svg=els['edge-layer'];svg.replaceChildren();for(const e of edges){const a=positions[e.from],b=positions[e.to];if(!a||!b)continue;
 const p=document.createElementNS('http://www.w3.org/2000/svg','path');let x1=a.x+NODE_W,y1=a.y+NODE_H*.5,x2=b.x,y2=b.y+NODE_H*.5;
 if(x2<=x1+40){y1=a.y+NODE_H;y2=b.y; x1=a.x+NODE_W*.5;x2=b.x+NODE_W*.5;}
 const bend=(x2-x1)*.42;
 p.setAttribute('d',`M ${x1} ${y1} C ${x1+bend} ${y1}, ${x2-bend} ${y2}, ${x2} ${y2}`);
 p.setAttribute('class','edge '+e.type);svg.appendChild(p);const label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x',(x1+x2)/2);label.setAttribute('y',(y1+y2)/2-5);label.setAttribute('class','edge-label');label.textContent=({fork:'分支',parent:'父子',manual:'手动关联',handoff:'交接',reference:'引用'})[e.type]+(e.evidence?' · '+e.evidence:'');svg.appendChild(label);
 }}
function render(){calculateLayout();els.nodes.replaceChildren();els.viewport.style.width=worldW+'px';els.viewport.style.height=worldH+'px';els.edges.setAttribute('viewBox',`0 0 ${worldW} ${worldH}`);els.edges.style.width=worldW+'px';els.edges.style.height=worldH+'px';
 for(const lane of laneHeaders){const e=text('div','lane-header','');e.style.left='65px';e.style.top=lane.y+'px';e.append(text('span','lane-icon','⌁'),text('span','',lane.name),text('small','',lane.count+' SESSIONS'));els.nodes.appendChild(e);}
 for(const s of visible)els.nodes.appendChild(makeNode(s));if(!visible.length){els.nodes.append(text('div','empty',query?'没有找到相关 Session':'此项目没有已记录的本地 Session'));}
 drawEdges();drawInspector();if(linkingChild)els.inspector.classList.remove('visible');els.stats.textContent=`${visible.length} SESSIONS · ${laneHeaders.length} PROJECTS · ${edges.length} LINKS`;
 const cloud=data.chatgptSource||{status:'unconfigured'};
 els.status.textContent=data.demo?'DEMO DATA · NOT CONNECTED':
  `LOCAL · METADATA ONLY · CHATGPT ${String(cloud.status).toUpperCase()} · ${cloud.source||'no source'}`;
 els.status.title=[cloud.exportedAt&&('Snapshot '+cloud.exportedAt),cloud.complete?'Complete':'Not verified complete',...(cloud.warnings||[])].filter(Boolean).join(' · ');
 els.notice.textContent=data.skippedCompressed ? `有 ${data.skippedCompressed} 个压缩会话未读取：请安装 zstandard 并刷新` : linkingChild?'点击另一个节点，建立手动父子关联 · 按 Esc 取消':'拖动画布以平移 · 滚轮缩放 · 拖动卡片自由布局';
}
function applyCamera(){els.viewport.style.transform=`translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`;els['zoom-value'].textContent=Math.round(camera.scale*100)+'%';}
function fit(){const rect=els.board.getBoundingClientRect();camera.scale=Math.min(1.1,Math.max(.18,Math.min((rect.width-90)/worldW,(rect.height-80)/worldH)));
 camera.x=Math.max(8,(rect.width-worldW*camera.scale)/2);camera.y=18;applyCamera();}
function zoom(next,cx,cy){const rect=els.board.getBoundingClientRect();const x=(cx??(rect.left+rect.width/2))-rect.left, y=(cy??(rect.top+rect.height/2))-rect.top;const old=camera.scale;camera.scale=Math.min(2.25,Math.max(.17,next));camera.x=x-(x-camera.x)*camera.scale/old;camera.y=y-(y-camera.y)*camera.scale/old;applyCamera();}
let canvasDrag=null;
els.board.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('.node'))return;canvasDrag={x:e.clientX,y:e.clientY,ox:camera.x,oy:camera.y};els.board.classList.add('grabbing');els.board.setPointerCapture(e.pointerId);});
els.board.addEventListener('pointermove',e=>{if(!canvasDrag)return;camera.x=canvasDrag.ox+e.clientX-canvasDrag.x;camera.y=canvasDrag.oy+e.clientY-canvasDrag.y;applyCamera();});
els.board.addEventListener('pointerup',()=>{canvasDrag=null;els.board.classList.remove('grabbing');});
els.board.addEventListener('wheel',e=>{e.preventDefault();zoom(camera.scale*(e.deltaY<0?1.13:.885),e.clientX,e.clientY);},{passive:false});
function selectSession(id){selected=id;drawInspector();for(const el of els.nodes.querySelectorAll('.node'))el.classList.toggle('selected',el.dataset.id===id);}
function drawInspector(){const s=byId(selected);els.inspector.classList.toggle('visible',!!s);if(!s)return;els['detail-title'].textContent=s.name;
 const fields=[['Session ID',s.id],['Source',s.source==='chatgpt'?'ChatGPT · user-provided snapshot':'Codex local'],['Project',projectName(s.project)],['Working directory',s.cwd||'unknown'],['Created',s.created?briefDate(s.created):'unknown'],['Fork from',s.forkedFrom||'—'],['Parent thread',s.parentThread||'—'],['手动关系', (manual[s.id]||[]).map(m=>`${m.type}: ${m.from}`).join('；')||'—'],['Archived',s.archivedKnown===false?'未知':s.archived?'是':'否']];
 els['open-desktop'].disabled=s.source==='chatgpt';els['copy-resume'].disabled=s.source==='chatgpt';
 const wrap=els['detail-meta'];wrap.replaceChildren();for(const [a,b] of fields){const d=document.createElement('div');d.append(text('b','',a+': '),document.createTextNode(b));wrap.append(d);}
}
function openDesktop(id){if(!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(id))return;window.location.href='codex://threads/'+id;}
function resumeCommand(s){const cwd=s.cwd||s.project;return (navigator.platform.toLowerCase().includes('win')?`Set-Location -LiteralPath '${cwd.replaceAll("'","''")}'; codex resume ${s.id}`:`cd ${"'"+cwd.replaceAll("'","'\\''")+"'"} && codex resume ${s.id}`);}
async function copy(value){try{await navigator.clipboard.writeText(value);showToast('已复制到剪贴板');}catch{const t=document.createElement('textarea');t.value=value;document.body.append(t);t.select();document.execCommand('copy');t.remove();showToast('已复制');}}
els['open-desktop'].addEventListener('click',()=>{const s=byId(selected);if(s&&s.source!=='chatgpt'&&!data.demo)openDesktop(s.id);else showToast('没有受支持的跳转');});
els['copy-resume'].addEventListener('click',()=>{const s=byId(selected);if(s&&s.source!=='chatgpt'&&!data.demo)copy(resumeCommand(s));else showToast('演示会话不可恢复');});
els['link-parent'].addEventListener('click',()=>{if(!selected)return;const choice=prompt('关系类型：输入 1（交接）、2（引用）、3（其他手动关联）', '1'); if(choice===null)return; const types={'1':'handoff','2':'reference','3':'manual'}; if(!types[choice]){showToast('请输入 1、2 或 3');return;} linkingType=types[choice]; linkingChild=selected;els.inspector.classList.remove('visible');els.board.classList.add('linking');render();});
els['unlink-parent'].addEventListener('click',()=>{if(!selected)return;if(!manual[selected]?.length){showToast('没有手动关联');return;} if(!confirm('删除此会话的全部手动关联？自动识别的关系不会删除。'))return; delete manual[selected];saveStored('manual',manual);showToast('手动关联已取消');render();});
document.getElementById('close-inspector').addEventListener('click',()=>{selected=null;els.inspector.classList.remove('visible');render();});
els.search.addEventListener('input',()=>{query=els.search.value.trim().toLocaleLowerCase();render();fit();});
window.addEventListener('keydown',ev=>{if(ev.key==='Escape'){linkingChild=null;els.board.classList.remove('linking');render();}else if(ev.key==='/'&&document.activeElement!==els.search){ev.preventDefault();els.search.focus();}});
document.getElementById('zoom-in').addEventListener('click',()=>zoom(camera.scale*1.2));
document.getElementById('zoom-out').addEventListener('click',()=>zoom(camera.scale/1.2));
document.getElementById('fit').addEventListener('click',fit);
document.getElementById('reset').addEventListener('click',()=>{layoutPositions={};saveStored('positions',{});render();fit();showToast('布局已重置');});
els.refresh.addEventListener('click',async()=>{if(!data.live){showToast('静态导出文件：请重新运行 canvas.py 生成最新快照');return;}try{const r=await fetch('/api/data',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);const latest=await r.json();data={...latest,live:true,csrfToken:data.csrfToken};if(focus!=='all'&&!data.projects.some(p=>p.id===focus)&&!focus.startsWith('session:'))focus='all';drawSidebar();render();showToast('已重新读取本地 Session 和配置的 ChatGPT 快照');}catch{showToast('刷新失败：本地服务可能已停止');}});
window.addEventListener('resize',()=>{if(document.hasFocus())applyCamera();});
window.codexCanvas = {
  getData: () => data,
  selectProject,
  setData: next => { data=next; if(focus!=='all'&&!data.projects.some(p=>p.id===focus)&&!focus.startsWith('session:'))focus='all'; drawSidebar();render();fit(); }
};
drawSidebar();render();fit();
})();
