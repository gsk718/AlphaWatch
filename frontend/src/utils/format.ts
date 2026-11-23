export const money=(n:number|undefined|null)=>n==null?'—':new Intl.NumberFormat('en-US',{style:'currency',currency:'USD',maximumFractionDigits:2}).format(n);
export const percent=(n:number|undefined|null)=>n==null?'—':`${(n*100).toFixed(2)}%`;
export const date=(s:string|undefined)=>s?new Date(`${s.slice(0,10)}T12:00:00`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}):'—';
