"""Exercise the actual C# PythonSession bridge against a harmless JSONL worker.

Creates a standalone console project in test-output; no WPF, models, live library
or production Python worker is used. The C# bridge source is linked, not copied.
"""
import json
from pathlib import Path
import subprocess
import sys
import uuid
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
WORKER=r'''
import json,os,sys,time
from pathlib import Path
for line in sys.stdin:
    request=json.loads(line);command=request['command'];root=Path(request['root']);root.mkdir(parents=True,exist_ok=True)
    with (root/'requests.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps({'pid':os.getpid(),'command':command,'id':request['request_id']})+'\n')
    if command=='mutate_bad':
        with (root/'mutations.jsonl').open('a',encoding='utf8') as stream:stream.write(request['request_id']+'\n')
    if command in ['malformed','mutate_bad']:
        print('NOT JSON',flush=True);continue
    if command=='delay':time.sleep(request.get('seconds',2))
    reply={'request_id':'wrong-id' if command=='mismatch' else request['request_id'],'ok':command!='fail','result':{'pid':os.getpid(),'value':request.get('value')},'error':'Synthetic application failure'}
    print(json.dumps(reply),flush=True)
'''
PROGRAM=r'''
using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using ArchiveReader;

var python=args[0];var root=args[1];var worker=args[2];Directory.CreateDirectory(root);
var outcomes=new List<object>();
void Check(bool value,string message){if(!value)throw new Exception(message);}
async Task Case(string name,Func<Task> test){var watch=Stopwatch.StartNew();await test();outcomes.Add(new{name,passed=true,seconds=watch.Elapsed.TotalSeconds});}
int Pid(JsonNode value)=>value["pid"]!.GetValue<int>();
PythonSession Session(string name)=>new(python,Path.Combine(root,name),worker);

await Case("same_pid_reuse_and_concurrent_serialization",async()=>{
 using var session=Session("reuse");int pid=Pid(await session.CallAsync("echo"));
 Check(Pid(await session.CallAsync("echo"))==pid,"Worker was not reused");
 var calls=Enumerable.Range(0,8).Select(async i=>{var result=await session.CallAsync("delay",new(){["seconds"]=.03,["value"]=i});Check(Pid(result)==pid,"Concurrent call restarted worker");Check(result["value"]!.GetValue<int>()==i,"Concurrent replies crossed");}).ToArray();await Task.WhenAll(calls);
});
await Case("application_error_does_not_restart",async()=>{
 using var session=Session("application");int before=Pid(await session.CallAsync("echo"));bool caught=false;
 try{await session.CallAsync("fail");}catch(Exception ex){caught=ex.Message.Contains("Synthetic application failure");}
 Check(caught,"Application error not propagated");Check(Pid(await session.CallAsync("echo"))==before,"Application failure restarted worker");
});
await Case("timeout_kills_and_next_call_restarts",async()=>{
 using var session=Session("timeout");int before=Pid(await session.CallAsync("echo"));bool caught=false;
 try{await session.CallAsync("delay",new(){["seconds"]=3,["timeout"]=1});}catch(TimeoutException){caught=true;}
 Check(caught,"Expected timeout");Check(Pid(await session.CallAsync("echo"))!=before,"Timed out worker reused");
});
await Case("cancellation_kills_and_next_call_restarts",async()=>{
 using var session=Session("cancel");int before=Pid(await session.CallAsync("echo"));using var token=new CancellationTokenSource(TimeSpan.FromMilliseconds(100));bool caught=false;
 try{await session.CallAsync("delay",new(){["seconds"]=3},token.Token);}catch(OperationCanceledException){caught=true;}
 Check(caught,"Expected cancellation");Check(Pid(await session.CallAsync("echo"))!=before,"Cancelled worker reused");
});
foreach(var bad in new[]{"malformed","mismatch","mutate_bad"})await Case(bad+"_kills_without_replay",async()=>{
 var folder=Path.Combine(root,bad);using var session=Session(bad);int before=Pid(await session.CallAsync("echo"));bool caught=false;
 try{await session.CallAsync(bad,new(){["private_text"]="PRIVATE-PAYLOAD-MUST-NOT-APPEAR"});}catch(IOException){caught=true;}
 Check(caught,"Expected transport failure: "+bad);Check(Pid(await session.CallAsync("echo"))!=before,"Broken transport worker reused");
 var requests=File.ReadAllLines(Path.Combine(folder,"requests.jsonl")).Select(line=>JsonNode.Parse(line)!).ToList();Check(requests.Count(r=>r["command"]!.ToString()==bad)==1,"Request was replayed after broken transport");
 if(bad=="mutate_bad")Check(File.ReadAllLines(Path.Combine(folder,"mutations.jsonl")).Length==1,"Mutation replayed");
 var logs=Directory.GetFiles(Path.Combine(folder,"diagnostics"),"*.log");Check(logs.Length==1,"Missing transport diagnostics");Check(!File.ReadAllText(logs[0]).Contains("PRIVATE-PAYLOAD-MUST-NOT-APPEAR"),"Diagnostics exposed request payload");
});
await Case("twenty_four_request_recycle",async()=>{
 using var session=Session("recycle");int first=0;
 for(int i=0;i<24;i++){int pid=Pid(await session.CallAsync("echo"));if(i==0)first=pid;Check(pid==first,"Worker recycled before 24 requests");}
 Check(Pid(await session.CallAsync("echo"))!=first,"Worker not recycled after 24 requests");
});
Console.WriteLine(JsonSerializer.Serialize(new{passed=true,tests=outcomes}));

namespace ArchiveReader{internal static class Localizer{public static string Text(string value)=>value;}}
'''


def main():
    output=ROOT/'test-output'/'session-bridge'/uuid.uuid4().hex;output.mkdir(parents=True)
    project=output/'BridgeHarness.csproj';source=ROOT/'src/ArchiveReader.Desktop/PythonSession.cs'
    project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup><ItemGroup><Compile Include="'+escape(str(source),{'"':'&quot;'})+'" Link="PythonSession.cs" /></ItemGroup></Project>',encoding='utf8')
    (output/'Program.cs').write_text(PROGRAM,encoding='utf8');(output/'model_session.py').write_text(WORKER,encoding='utf8')
    build=subprocess.run(['dotnet','build',str(project),'-c','Release','--nologo'],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=120)
    (output/'build.log').write_text(build.stdout+build.stderr,encoding='utf8')
    if build.returncode:raise RuntimeError('Bridge harness build failed: '+str(output/'build.log'))
    run=subprocess.run(['dotnet',str(output/'bin/Release/net10.0/BridgeHarness.dll'),sys.executable,str(output/'fixtures'),str(output)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=90)
    (output/'run.log').write_text(run.stdout+run.stderr,encoding='utf8')
    if run.returncode:raise RuntimeError('Bridge harness failed: '+str(output/'run.log'))
    result=json.loads(run.stdout.strip().splitlines()[-1]);result.update(source=str(source),project=str(project),policy='Synthetic fake worker; production C# bridge linked unchanged; no neural inference.')
    report=output/'report.json';report.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps({'passed':result['passed'],'tests':len(result['tests']),'report':str(report)}),flush=True)

if __name__=='__main__':main()
