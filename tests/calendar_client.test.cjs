const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../habit_tracker/static/calendar.js'),'utf8');
function setup(responses) {
  const attrs={'aria-pressed':'false'};
  const fields={};
  const dl={hidden:false},unknown={hidden:true};
  const classes={add(){},remove(){},toggle(){}};
  const button={dataset:{habitId:'1',name:'Read',displayDate:'15.11.2026',date:'2026-11-15',url:'/habits/1/completion?year=2026&month=11'},disabled:false,classList:classes,textContent:'·',
    getAttribute:k=>attrs[k],setAttribute:(k,v)=>attrs[k]=v,removeAttribute:k=>delete attrs[k]};
  const panel={classList:classes,setAttribute(){},removeAttribute(){},querySelector(selector){
    if(selector==='dl')return dl;
    if(selector==='.stats-unknown')return unknown;
    return fields[selector]??=( {textContent:'old'} );
  }};
  let handler;
  const calendar={dataset:{csrf:'test-token'},addEventListener(type,fn){handler=fn},querySelectorAll:()=>[button]};
  const status={textContent:''},reload={hidden:true};
  const document={querySelector(selector){return selector==='.calendar'?calendar:selector==='#calendar-status'?status:selector==='#calendar-reload'?reload:panel}};
  const requests=[];
  vm.runInNewContext(source,{document,window:{location:{origin:'http://localhost'}},URL,AbortController,setTimeout,clearTimeout,
    fetch:async(url,options)=>{requests.push({url:String(url),options});const response=responses.shift();if(response instanceof Error)throw response;return response;}});
  return {button,panel,fields,dl,unknown,status,reload,requests,attrs,click:()=>handler({target:{closest:()=>button}})};
}
function response(completed,count) {
  return {ok:true,json:async()=>({completed,archived:false,stats:{completed_days:count,available_days:15,percentage:count?7:0,current_streak:count,best_streak:count}})};
}
test('failed POST reconciles truthful state; retry saves mark and statistics',async()=>{
  const state=setup([{ok:false},response(false,0),response(true,1)]);
  await state.click();
  assert.equal(state.attrs['aria-pressed'],'false');
  assert.equal(state.button.disabled,false);
  assert.match(state.status.textContent,/не подтверждён/);
  assert.ok(!state.status.textContent.includes('показатели сохранены'));
  assert.match(state.requests[1].url,/year=2026&month=11&date=2026-11-15/);
  await state.click();
  assert.equal(state.attrs['aria-pressed'],'true');
  assert.equal(state.fields['[data-stat="completed_days"]'].textContent,'1');
  assert.match(state.status.textContent,/сохранены/);
});
test('lost response after committed write reconciles actual mark',async()=>{
  const state=setup([new Error('lost response'),response(true,1)]);
  await state.click();
  assert.equal(state.attrs['aria-pressed'],'true');
  assert.equal(state.button.disabled,false);
  assert.match(state.status.textContent,/сверены/);
});
test('disconnected POST and GET hide unconfirmed values and require refresh',async()=>{
  const state=setup([new Error('offline'),new Error('offline')]);
  await state.click();
  assert.equal(state.button.textContent,'?');
  assert.equal(state.button.disabled,true);
  assert.equal(state.dl.hidden,true);
  assert.equal(state.unknown.hidden,false);
  assert.equal(state.reload.hidden,false);
  assert.match(state.status.textContent,/Не удалось проверить/);
  assert.ok(!state.status.textContent.includes('показатели сохранены'));
});
