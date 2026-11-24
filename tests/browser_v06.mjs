/* v0.6 real-browser smoke against synthetic local files. No user account or sessions touched. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const root=mkdtempSync(join(tmpdir(),"codex-v06-"));
const localId="123e4567-e89b-42d3-a456-426614174099";
const sourceFile=join(root,"snapshot.json");
const home=join(root,".codex"),cwd=join(root,"work");
function source(title="Cloud A"){
 return {schema:"codex-session-canvas.chatgpt-metadata",version:1,
  scope:"user-provided-metadata",exportedAt:"2026-11-24T12:00:00Z",
  pages:[{page:1,complete:false,projects:[{id:"mirror-id",title:"AI-Skills/Agents"}],
   conversations:[{id:"cloud-a",projectId:"mirror-id",title,archived:false},
                  {id:"cloud-b",projectId:"mirror-id",title:"Cloud B"}],
   relationships:[{from:"cloud-a",to:"cloud-b",type:"reference",evidence:"user-confirmed"}]}]};
}
let server;
try{
 mkdirSync(cwd);
 const sess=join(home,"sessions","2026","11","24");mkdirSync(sess,{recursive:true});
 writeFileSync(join(sess,`rollout-${localId}.jsonl`),
  [JSON.stringify({type:"session_meta",payload:{meta:{id:localId,cwd,timestamp:"2026-11-24T12:00:00Z"}}}),
   JSON.stringify({type:"event_msg",payload:{message:"SECRET CHAT BODY MUST NEVER APPEAR"}})].join("\n")+"\n");
 writeFileSync(sourceFile,JSON.stringify(source()));
 const cfg=join(root,"projects.json");
 writeFileSync(cfg,JSON.stringify({version:1,projects:[{id:"local",name:"Legacy",folders:[cwd],chatgptProjectId:"mirror-id"}],relationships:[]}));
 const exported=join(root,"export.html");
 const proc=spawnSync("python",["canvas.py","--codex-home",home,"--config",cfg,
  "--chatgpt-snapshot",sourceFile,"--export","--output",exported],{encoding:"utf8"});
 assert.equal(proc.status,0,proc.stderr);
 assert(!readFileSync(exported,"utf8").includes("SECRET CHAT BODY MUST NEVER APPEAR"));
 server=spawn("python",["-u","canvas.py","--serve","--port","0","--codex-home",home,
  "--config",cfg,"--chatgpt-snapshot",sourceFile,"--project",cwd],{stdio:["ignore","pipe","pipe"]});
 const url=await new Promise((resolve,reject)=>{
  let output="";const timer=setTimeout(()=>reject(Error("server startup timed out "+output)),15000);
  server.stdout.on("data",data=>{output+=String(data);const match=output.match(/http:\/\/127\.0\.0\.1:\d+\//);
    if(match){clearTimeout(timer);resolve(match[0]);}});
  server.once("exit",code=>reject(Error("server exited "+code)));
 });
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1500,height:900}});
  const errors=[];page.on("pageerror",err=>errors.push(String(err)));
  page.on("dialog",dialog=>dialog.accept("2"));
  await page.goto(url,{waitUntil:"load"});
  assert(await page.locator("#project-list").getByText("AI-Skills/Agents").count());
  assert.equal(await page.locator(".node.cloud").count(),2);
  assert.equal(await page.locator(".node:not(.cloud)").count(),1);
  assert.equal(await page.locator(".edge.reference").count(),1);
  assert((await page.locator("#status").textContent()).includes("INCOMPLETE"));
  assert(!await page.content().then(html=>html.includes("SECRET CHAT BODY MUST NEVER APPEAR")));
  await page.locator(".node.cloud").first().click();
  assert(await page.locator("#open-desktop").isDisabled());
  assert(await page.locator("#copy-resume").isDisabled());
  await page.locator("#link-parent").click();
  await page.locator(".node:not(.cloud)").first().click();
  assert.equal(await page.locator(".edge.reference").count(),2);
  await page.reload();
  assert.equal(await page.locator(".edge.reference").count(),2);
  writeFileSync(sourceFile,JSON.stringify(source("Renamed Cloud A")));
  await page.locator("#refresh").click();
  await page.locator(".node.cloud").getByText("Renamed Cloud A").waitFor({timeout:10000});
  writeFileSync(sourceFile,JSON.stringify({bad:"SECRET CONTENT"}));
  await page.locator("#refresh").click();
  await page.waitForFunction(()=>document.querySelector("#status")?.textContent.includes("INVALID"),null,{timeout:10000});
  assert.equal(await page.locator(".node:not(.cloud)").count(),1);
  assert.equal(await page.locator(".node.cloud").count(),0);
  assert.equal(errors.length,0,errors.join("\n"));
  console.log("PASS v0.6 browser: merged cards, provenance, manual persistence, refresh, invalid source and privacy");
 } finally {await browser.close();}
} finally {
 if(server){server.kill();await new Promise(resolve=>{
  if(server.exitCode!==null||server.signalCode!==null)return resolve();
  server.once("exit",resolve);setTimeout(resolve,2000).unref();
 });}
 rmSync(root,{recursive:true,force:true});
}
