/* Browser smoke: real local Python server, Chromium, context editor and opt-in preview. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root=mkdtempSync(join(tmpdir(),"codex-context-browser-"));
try {
const cwd=join(root,"work");mkdirSync(cwd);
const home=join(root,".codex"),session=join(home,"sessions","2026","11","23");
mkdirSync(session,{recursive:true});
const sid="123e4567-e89b-42d3-a456-426614174099";
const payload=[
  {type:"session_meta",payload:{meta:{id:sid,cwd,timestamp:"2026-11-23T02:00:00Z"}}},
  {type:"response_item",payload:{type:"message",role:"user",content:[{type:"input_text",text:"PRIVATE SOURCE CONTENT FOR OPT-IN"}]}},
  {type:"response_item",payload:{type:"message",role:"assistant",content:[{type:"output_text",text:"Context confirmed"}]}}
];
writeFileSync(join(session,"rollout-2026-11-23-"+sid+".jsonl"),payload.map(JSON.stringify).join("\n")+"\n","utf8");
writeFileSync(join(home,"session_index.jsonl"),JSON.stringify({id:sid,thread_name:"Test Source Session"})+"\n");
const out=join(root,"export.html");
const exported=spawnSync("python",["canvas.py","--codex-home",home,"--config",join(root,"projects.json"),"--output",out,"--export"],{encoding:"utf8"});
assert.equal(exported.status,0,exported.stderr);
assert(!readFileSync(out,"utf8").includes("PRIVATE SOURCE CONTENT FOR OPT-IN"),"Static HTML must not leak source body");
const server=spawn("python",["-u","canvas.py","--serve","--port","0","--codex-home",home,"--config",join(root,"projects.json")],{stdio:["ignore","pipe","pipe"]});
let url;
try {
  url=await new Promise((resolve,reject)=>{
    let acc="";
    const timer=setTimeout(()=>reject(Error("Server startup timeout "+acc)),15000);
    server.stdout.on("data",buf=>{acc+=buf.toString();const match=acc.match(/http:\/\/127\.0\.0\.1:\d+\//);
      if(match){clearTimeout(timer);resolve(match[0]);}});
    server.on("exit",c=>reject(Error("server exited "+c)));
  });
  const browser=await chromium.launch({headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1650,height:980}});
    page.on("dialog",d=>d.accept());
    const jsErrors=[];page.on("pageerror",err=>jsErrors.push(String(err)));
    await page.goto(url,{waitUntil:"load"});
    assert.equal(await page.locator("#initial-data").count(),1);
    const init=await page.evaluate(()=>JSON.parse(document.getElementById("initial-data").textContent));
    assert.equal(init.sessions.length,1);
    assert(!await page.content().then(x=>x.includes("PRIVATE SOURCE CONTENT FOR OPT-IN")));
    await page.getByRole("button",{name:/Project Graph/}).click();
    assert(await page.locator("#project-graph").isVisible());
    await page.getByRole("button",{name:/Session Graph/}).click();
    await page.getByRole("button",{name:/Context Graph/}).click();
    assert(await page.locator(".ctx-overlay").isVisible());
    await page.getByRole("button",{name:/Linked Context/}).click();
    await page.waitForFunction(()=>document.querySelector(".ctx-editor")?.textContent.includes("LINKED CONTEXTS"),null,{timeout:10000});
    assert(!await page.content().then(x=>x.includes("PRIVATE SOURCE CONTENT FOR OPT-IN")),
      "Linked Context browsing must not read conversation bodies");
    await page.getByRole("button",{name:"+ Source"}).click();
    await page.getByRole("button",{name:"+ Selector"}).click();
    assert.equal(await page.locator(".ctx-node").count(),2);
    await page.locator(".ctx-node").nth(0).locator(".ctx-out").dragTo(
      page.locator(".ctx-node").nth(1).locator(".ctx-in"),{timeout:12000});
    assert.equal(await page.locator(".ctx-wire").count(),1,"Drag-to-connect must create an edge");
    await page.getByRole("button",{name:"保存",exact:true}).click();
    await page.waitForTimeout(350);
    const graph={
      version:1,id:"main",projectId:"all",revision:1,
      nodes:[
        {id:"s",type:"session_source",x:70,y:75,config:{sessionId:sid}},
        {id:"a",type:"selector",x:350,y:75,config:{mode:"selected",segmentIds:["turn-0"]}},
        {id:"m",type:"merge",x:630,y:75,config:{budget:2000}},
        {id:"t",type:"new_session",x:920,y:75,config:{cwd,task:"Task from browser smoke",budget:2000}}
      ],
      edges:[
        {from:"s",to:"a",out:"out",in:"source"},
        {from:"a",to:"m",out:"out",in:"in"},
        {from:"m",to:"t",out:"out",in:"in"}
      ]
    };
    const saved=await page.evaluate(async({graph,token})=>{
      const r=await fetch("/api/context/graph",{method:"POST",headers:{"Content-Type":"application/json","X-Canvas-CSRF":token},body:JSON.stringify({graph})});
      return {status:r.status,body:await r.json()};
    },{graph,token:init.csrfToken});
    assert.equal(saved.status,200,JSON.stringify(saved.body));
    await page.reload();
    await page.getByRole("button",{name:/Context Graph/}).click();
    await page.waitForTimeout(400);
    assert.equal(await page.locator(".ctx-node").count(),4);
    await page.locator(".ctx-node").nth(1).click();
    await page.getByRole("button",{name:/明确授权读取此 Session/}).click();
    await page.waitForTimeout(250);
    assert.equal(await page.locator(".ctx-segment").count(),2);
    const filter=page.locator("input[placeholder='仅搜索当前已授权读取的片段']");
    await filter.fill("PRIVATE");
    assert.equal(await page.locator(".ctx-segment:visible").count(),1);
    await filter.fill("NOT-A-MATCH");
    assert.equal(await page.locator(".ctx-segment:visible").count(),0);
    await page.getByRole("button",{name:"预览",exact:true}).click();
    await page.waitForTimeout(500);
    const displayed=await page.locator(".ctx-editor textarea").inputValue();
    assert(displayed.includes("PRIVATE SOURCE CONTENT FOR OPT-IN"));
    assert(displayed.includes("Task from browser smoke"));
    await page.locator(".ctx-editor textarea").fill(displayed.replace(
      "PRIVATE SOURCE CONTENT FOR OPT-IN","[REDACTED]"));
    await page.getByRole("button",{name:/应用脱敏修改/}).click();
    await page.waitForTimeout(300);
    assert((await page.locator(".ctx-status").textContent()).includes("脱敏修改已应用"));
    assert.equal(jsErrors.length,0,jsErrors.join("\n"));
    await page.screenshot({path:join(root,"context-smoke.png")});
    console.log("PASS browser smoke: export, drag-to-connect, 3 views, save/reload, consent preview and in-memory redaction");
  } finally {
    await browser.close();
  }
} finally {
  server.kill();
  await new Promise(resolve=>{
    if(server.exitCode!==null||server.signalCode!==null)return resolve();
    server.once("exit",resolve);
    setTimeout(resolve,2000).unref();
  });
}
} finally {
  rmSync(root,{recursive:true,force:true});
}
