/* Logical Project Graph v0.2. Session rendering remains owned by app.js. */
(() => {
'use strict';
const root = document.querySelector('.main');
const bar = document.querySelector('.toolbar');
const sessionBoard = document.getElementById('board');
const sessionZoom = document.querySelector('.zoom');
const sessionNote = document.getElementById('notice');
const existing = window.codexCanvas;
if (!existing) return;
const el = (tag, cls, content = '') => { const e = document.createElement(tag);if(cls)e.className=cls;e.textContent=content;return e; };
const trigger = el('button','tool-btn','⌘ Project Graph'); trigger.id='project-graph-toggle';
bar.insertBefore(trigger,bar.firstChild);
const overlay = el('section','project-graph-overlay'); overlay.id='project-graph';overlay.hidden=true;
const controls = el('div','pg-controls');
const addBtn=el('button','tool-btn','＋ 新建项目');
const saveBtn=el('button','tool-btn','保存项目配置');
const exportBtn=el('button','tool-btn','导出 JSON');
const backBtn=el('button','tool-btn','↩ Session Graph');
controls.append(addBtn,saveBtn,exportBtn,backBtn);
const info=el('span','pg-message','项目继承边 ≠ Session Fork 或上下文引用');controls.append(info);
overlay.append(controls);
const stage=el('div','pg-stage');stage.id='project-stage';
const world=el('div','pg-world');
const lines=document.createElementNS('http://www.w3.org/2000/svg','svg');lines.setAttribute('class','pg-lines');
world.append(lines);const cards=el('div','pg-cards');world.append(cards);stage.append(world);overlay.append(stage);
const editor=el('aside','pg-editor');
const heading=el('div','pg-editor-heading','PROJECT INSPECTOR');
const nameLabel=el('label','','名称');const nameInput=el('input','pg-input');nameInput.id='pg-name';
const idLabel=el('label','','稳定 ID（创建后不可更改）');const idInput=el('input','pg-input');idInput.id='pg-id';
const folderLabel=el('label','','关联文件夹（每行一个绝对路径）');const folderInput=el('textarea','pg-input');folderInput.id='pg-folders';folderInput.rows=5;
const hint=el('small','','仅编辑逻辑项目配置；不会移动或删除磁盘上的项目文件夹或 Codex Session。');
const removeBtn=el('button','pg-danger','删除此逻辑项目');
const linkBtn=el('button','tool-btn','连线 → 选择后继项目');
const unlinkLabel=el('label','','前驱项目关系');const links=el('div','pg-related');
editor.append(heading,nameLabel,nameInput,idLabel,idInput,folderLabel,folderInput,hint,linkBtn,unlinkLabel,links,removeBtn);
overlay.append(editor);root.append(overlay);
let open=false,selected=null,linkFrom=null,drag=null;
let registry={version:1,projects:[],relationships:[]};
let pan={x:50,y:50,z:1},coords={};
let initClone = null;
const projectId = p=>'logical:'+p.id;
const data=()=>existing.getData();
function toast(s,isError=false){info.textContent=s;info.classList.toggle('pg-error',isError);}
function deepClone(obj){return JSON.parse(JSON.stringify(obj));}
function fromData(){const current=data();registry=deepClone(current.registry || {version:1,projects:[],relationships:[]});initClone=JSON.stringify(registry);}
function isDirty(){return JSON.stringify(registry)!==initClone;}
function applyPan(){world.style.transform=`translate(${pan.x}px,${pan.y}px) scale(${pan.z})`;}
function switchMode(next){if(open===next)return;if(!next && isDirty()&&!confirm('项目配置有未保存修改。确定离开？'))return;
 open=next;overlay.hidden=!open;sessionBoard.style.display=open?'none':'';sessionZoom.style.display=open?'none':'';sessionNote.style.display=open?'none':'';
 trigger.textContent=open?'◈ Project Graph（当前）':'⌘ Project Graph';document.getElementById('inspector').style.display=open?'none':'';
 if(open){fromData();render();}}
trigger.addEventListener('click',()=>switchMode(!open));
backBtn.addEventListener('click',()=>switchMode(false));
function addProject(){const id=prompt('新项目 ID：字母、数字、点、下划线或连字符（创建后固定）','project-'+(registry.projects.length+1));if(!id)return;
 const name=prompt('项目名称',id);if(!name)return;
 if(!/^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(id)||registry.projects.some(x=>x.id===id)||id==='all'||id==='session')return toast('ID 格式错误或重复',true);
 registry.projects.push({id,name,folders:[]});selected=id;render();toast('已创建项目，请添加文件夹并点击保存');}
addBtn.addEventListener('click',addProject);
function updateSelected(){const p=registry.projects.find(x=>x.id===selected);if(!p)return;
 p.name=nameInput.value; p.folders=folderInput.value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 render(false);toast('本地草稿已更新，请点击保存');}
nameInput.addEventListener('change',updateSelected); folderInput.addEventListener('change',updateSelected);
function select(id){if(linkFrom){if(id===linkFrom)return toast('项目不能继承自身',true);
 if(!registry.relationships.some(e=>e.from===linkFrom&&e.to===id))registry.relationships.push({from:linkFrom,to:id,type:'successor'});
 linkFrom=null;stage.classList.remove('pg-linking');render();toast('已添加待保存的项目继承关系');return;}
 selected=id;render();}
linkBtn.addEventListener('click',()=>{if(!selected)return;linkFrom=selected;stage.classList.add('pg-linking');toast('请点击目标项目节点以创建“当前项目 → 后继项目”的连线');});
removeBtn.addEventListener('click',()=>{if(!selected)return;const p=registry.projects.find(x=>x.id===selected);
 if(!p||!confirm(`删除逻辑项目「${p.name}」？这不会删除任何文件夹或 Session。`))return;
 registry.projects=registry.projects.filter(x=>x.id!==selected);registry.relationships=registry.relationships.filter(x=>x.from!==selected&&x.to!==selected);selected=null;render();toast('项目已从配置草稿中移除；请点击保存');});
function downloadConfig(){const blob=new Blob([JSON.stringify(registry,null,2)+'\n'],{type:'application/json'});const href=URL.createObjectURL(blob);const a=el('a');a.href=href;a.download='projects.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(href),1000);}
exportBtn.addEventListener('click',downloadConfig);
async function save(){if(!data().live||data().demo){toast('静态演示只读：请导出 JSON 后使用本地 server 模式',true);return;}
 try{const res=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json','X-Canvas-CSRF':data().csrfToken},body:JSON.stringify(registry)});
 const result=await res.json();if(!res.ok)throw Error(result.error||'保存失败');
 existing.setData({...result.data,live:true,csrfToken:data().csrfToken});fromData();render();toast('项目配置已安全保存到本机');
 }catch(e){toast('保存被拒绝：'+e.message,true);}}
saveBtn.addEventListener('click',save);
function render(showEditor=true){
 cards.replaceChildren();lines.replaceChildren();const all=data().projects||[];
 const projects=[...registry.projects.map(p=>({...p,configured:true,id:projectId(p),count:all.find(q=>q.id===projectId(p))?.count||0})),
 ...all.filter(p=>!p.configured).map(p=>({...p,displayOnly:true}))];
 const graph=registry.relationships.map(e=>({from:projectId({id:e.from}),to:projectId({id:e.to})}));
 const child=new Map(projects.map(p=>[p.id,[]]));const indegree=new Map(projects.map(p=>[p.id,0]));
 for(const e of graph){if(child.has(e.from)&&indegree.has(e.to)){child.get(e.from).push(e.to);indegree.set(e.to,indegree.get(e.to)+1);}}
 const pending=projects.filter(p=>indegree.get(p.id)===0).map(p=>p.id);const levels=new Map(pending.map(id=>[id,0]));
 while(pending.length){const id=pending.shift();for(const next of child.get(id)||[]){levels.set(next,Math.max(levels.get(next)||0,(levels.get(id)||0)+1));indegree.set(next,indegree.get(next)-1);if(indegree.get(next)===0)pending.push(next);}}
 let byLevel=new Map();for(const p of projects){const d=levels.get(p.id)||0;if(!byLevel.has(d))byLevel.set(d,[]);byLevel.get(d).push(p);}
 coords={};let widest=0,tallest=0;
 for(const [d,group] of byLevel){group.forEach((p,i)=>{coords[p.id]={x:45+d*305,y:35+i*148};widest=Math.max(widest,45+d*305+255);tallest=Math.max(tallest,35+i*148+120);});}
 world.style.width=(widest+130)+'px';world.style.height=(tallest+130)+'px';lines.setAttribute('width',widest+130);lines.setAttribute('height',tallest+130);
 for(const e of graph){const a=coords[e.from],b=coords[e.to];if(!a||!b)continue;const path=document.createElementNS('http://www.w3.org/2000/svg','path');const x1=a.x+235,y1=a.y+53,x2=b.x,y2=b.y+53;path.setAttribute('d',`M${x1} ${y1} C${(x1+x2)/2} ${y1},${(x1+x2)/2} ${y2},${x2} ${y2}`);path.setAttribute('class','pg-edge');lines.append(path);}
 for(const p of projects){const c=el('div','pg-node'+(selected===p.id.replace(/^logical:/,'')?' pg-selected':''));c.style.left=coords[p.id].x+'px';c.style.top=coords[p.id].y+'px';c.dataset.id=p.id;
 const title=el('strong','',p.name);const details=el('small','',(p.folders?.length||0)+' 文件夹 · '+(p.count||0)+' Sessions');const raw=el('small','pg-folder-preview',(p.folders||[]).join(' · ')||'未绑定文件夹');const dock=el('span','pg-port','●');const out=el('span','pg-port pg-out','●');
 c.append(dock,title,out,details,raw);
 c.addEventListener('click',()=>{if(p.displayOnly){toast('自动发现的文件夹可先通过“新建项目”显式绑定',true);return;}select(p.id.slice(8));});
 c.addEventListener('dblclick',()=>{if(p.displayOnly){switchMode(false);existing.selectProject(p.id);return;}if(isDirty()){toast('先保存项目配置再进入 Session 视图',true);return;}switchMode(false);existing.selectProject(p.id);});
 cards.append(c);}
 if(showEditor)renderEditor();
}
function renderEditor(){const p=registry.projects.find(p=>p.id===selected);editor.style.display=p?'flex':'none';if(!p)return;
 nameInput.value=p.name;idInput.value=p.id;idInput.disabled=true;folderInput.value=p.folders.join('\n');links.replaceChildren();
 const incoming=registry.relationships.filter(e=>e.to===selected);if(!incoming.length)links.append(el('small','','暂无前驱项目'));
 for(const edge of incoming){const row=el('div','pg-link-item',edge.from+' → '+edge.to);const del=el('button','','×');del.title='删除这条项目继承边';del.addEventListener('click',()=>{registry.relationships=registry.relationships.filter(e=>e!==edge);render();toast('项目关系已从草稿移除');});row.append(del);links.append(row);}
}
let dragging=null;
stage.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('.pg-node'))return;dragging={x:e.clientX,y:e.clientY,px:pan.x,py:pan.y};stage.setPointerCapture(e.pointerId);});
stage.addEventListener('pointermove',e=>{if(!dragging)return;pan.x=dragging.px+e.clientX-dragging.x;pan.y=dragging.py+e.clientY-dragging.y;applyPan();});
stage.addEventListener('pointerup',()=>dragging=null);
stage.addEventListener('wheel',e=>{e.preventDefault();const r=stage.getBoundingClientRect();const px=e.clientX-r.left,py=e.clientY-r.top;const next=Math.max(.3,Math.min(2.3,pan.z*(e.deltaY<0?1.12:.89)));pan.x=px-(px-pan.x)*next/pan.z;pan.y=py-(py-pan.y)*next/pan.z;pan.z=next;applyPan();},{passive:false});
window.addEventListener('keydown',e=>{if(e.key==='Escape'&&linkFrom){linkFrom=null;stage.classList.remove('pg-linking');toast('已取消连线');}});
applyPan();
})();