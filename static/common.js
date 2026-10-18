const PAL=['#0ea5a4','#6366f1','#f59e0b','#ef4444','#8b5cf6','#10b981','#3b82f6','#ec4899','#64748b','#84cc16','#f97316','#06b6d4'];
Chart.defaults.font.family="Inter,'Segoe UI',system-ui,sans-serif";Chart.defaults.font.size=12;Chart.defaults.color='#64748b';
Chart.defaults.plugins.legend.labels.usePointStyle=true;Chart.defaults.maintainAspectRatio=false;Chart.defaults.animation.duration=450;
const fmtRp=v=>'Rp '+Math.round(v).toLocaleString('id-ID');
const fmtShort=v=>{const a=Math.abs(v);return a>=1e9?(v/1e9).toFixed(2)+' M':a>=1e6?(v/1e6).toFixed(1)+' jt':a>=1e3?(v/1e3).toFixed(0)+' rb':String(Math.round(v))};
const fmtN=(v,d=0)=>Number(v).toLocaleString('id-ID',{minimumFractionDigits:d,maximumFractionDigits:d});
const _ch={};
function mk(id,cfg){if(_ch[id])_ch[id].destroy();const el=document.getElementById(id);if(!el)return;_ch[id]=new Chart(el,cfg);return _ch[id]}
const gridY={grid:{color:'#eef2f7'},border:{display:false}};
const gridX={grid:{display:false},border:{display:false}};
function colorScale(v,lo,hi){ // putih→teal
  if(v==null)return '#f1f5f9';const t=Math.max(0,Math.min(1,(v-lo)/(hi-lo)));
  const a=[241,245,249],b=[14,165,164],c=[99,102,241];
  const m=t<.5?a.map((x,i)=>x+(b[i]-x)*t*2):b.map((x,i)=>x+(c[i]-x)*(t-.5)*2);
  return `rgb(${m.map(Math.round).join(',')})`}
function heatmap(el,h){
  if(!h){el.innerHTML='<p class="sub">Data terlalu sedikit untuk heatmap.</p>';return}
  const flat=h.z.flat().filter(x=>x!=null);const hi=Math.min(Math.max(...flat),3.5),lo=0.6;
  let s='<table class="heat"><tr><td></td>'+h.labels.map(l=>`<th>${l}</th>`).join('')+'</tr>';
  h.z.forEach((row,i)=>{s+=`<tr><td class="rl">${h.labels[i]}</td>`+row.map((v,j)=>`<td class="c" style="background:${colorScale(v,lo,hi)};color:${v!=null&&(v-lo)/(hi-lo)>.55?'#fff':'#0f172a'}" title="${h.labels[i]} + ${h.labels[j]}: lift ${v==null?'n/a (data terlalu sedikit)':v}">${v!=null&&v>=1.5?v.toFixed(1):''}</td>`}).join('')+'</tr>'});
  el.innerHTML=s+'</table>'}
function network(el,rules){
  const seen=new Set(),E=[];
  rules.forEach(r=>{if(r.a.includes(' + ')||r.c.includes(' + '))return;const k=[r.a,r.c].sort().join('|');if(seen.has(k))return;seen.add(k);E.push(r)});
  if(!E.length){el.innerHTML='<p class="sub">Tidak ada aturan pada parameter ini.</p>';return}
  const N=[...new Set(E.flatMap(r=>[r.a,r.c]))];const W=720,H=420,cx=W/2,cy=H/2,rx=W/2-110,ry=H/2-42;
  const pos={};N.forEach((n,i)=>{const t=2*Math.PI*i/N.length-Math.PI/2;pos[n]=[cx+rx*Math.cos(t),cy+ry*Math.sin(t)]});
  const lmax=Math.max(...E.map(r=>r.lift)),lmin=Math.min(...E.map(r=>r.lift));
  let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;max-height:430px">`;
  E.forEach(r=>{const[a,b]=[pos[r.a],pos[r.c]];const w=1.5+6*(r.lift-lmin)/((lmax-lmin)||1);
    s+=`<line x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" stroke="${colorScale(r.lift,1,lmax+.01)}" stroke-width="${w}" stroke-linecap="round" opacity=".8"><title>${r.a} ↔ ${r.c}\nlift ${r.lift.toFixed(2)} · conf ${(r.confidence*100).toFixed(1)}%</title></line>`;
    const mx=(a[0]+b[0])/2,my=(a[1]+b[1])/2;s+=`<text x="${mx}" y="${my}" font-size="10" fill="#334155" text-anchor="middle" paint-order="stroke" stroke="#fff" stroke-width="3">${r.lift.toFixed(2)}</text>`});
  N.forEach((n,i)=>{const[x,y]=pos[n];const left=x<cx;s+=`<circle cx="${x}" cy="${y}" r="9" fill="${PAL[i%PAL.length]}" stroke="#fff" stroke-width="2.5"/><text x="${x+(Math.abs(x-cx)<30?0:(left?-14:14))}" y="${y+(Math.abs(x-cx)<30?(y<cy?-16:24):4)}" font-size="12" font-weight="600" fill="#0f172a" text-anchor="${Math.abs(x-cx)<30?'middle':(left?'end':'start')}">${n}</text>`});
  el.innerHTML=s+'</svg>'}
function rulesTable(el,rules){
  if(!rules.length){el.innerHTML='<tr><td colspan="6" class="sub">Tidak ada aturan pada parameter/filter ini — turunkan min. support.</td></tr>';return}
  el.innerHTML=rules.map((r,i)=>`<tr><td>${i+1}</td><td><b>${r.a}</b></td><td>${r.c}</td><td class="r">${(r.support*100).toFixed(2)}%</td><td class="r">${(r.confidence*100).toFixed(1)}%</td><td class="r"><b>${r.lift.toFixed(2)}</b></td></tr>`).join('')}
