document.addEventListener('DOMContentLoaded', () => {
  const i18n = JSON.parse(document.getElementById('ui-messages').textContent);
  const menu = document.querySelector('[data-menu]');
  const closeMenu = () => { document.body.classList.remove('menu-open'); menu?.setAttribute('aria-expanded','false'); };
  menu?.addEventListener('click', () => { const open = document.body.classList.toggle('menu-open'); menu.setAttribute('aria-expanded', String(open)); });
  document.querySelector('[data-close-menu]')?.addEventListener('click', closeMenu);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeMenu();
    if (e.key === '/' && !['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) {
      const search = document.querySelector('#global-search'); if (search?.offsetParent) { e.preventDefault(); search.focus(); }
    }
  });
  document.querySelectorAll('[data-dismiss]').forEach(button => button.addEventListener('click', () => button.closest('.toast').remove()));
  const file = document.getElementById('excel-file'), zone = document.getElementById('dropzone');
  if (file && zone) {
    const showFile = () => {
      const selected = file.files[0];
      const label = document.getElementById('file-label');
      label.textContent = selected ? selected.name : i18n.dropFile;
      file.setCustomValidity(selected && (!selected.name.toLowerCase().endsWith('.xlsx') || selected.size > 10*1024*1024) ? i18n.fileError : '');
      if (selected) file.reportValidity();
    };
    file.addEventListener('change', showFile);
    ['dragenter','dragover'].forEach(event => zone.addEventListener(event, () => zone.classList.add('dragging')));
    ['dragleave','drop'].forEach(event => zone.addEventListener(event, () => zone.classList.remove('dragging')));
    document.getElementById('upload-form').addEventListener('submit', () => {
      const button = document.getElementById('upload-submit');button.disabled=true;button.textContent=i18n.checking;
    });
  }
  const calculation = document.querySelector('[data-kind="deliveries"]');
  if (calculation) {
    const format = (value, unit) => new Intl.NumberFormat(i18n.numberLocale, {maximumFractionDigits:unit==='kg'?3:2}).format(value) + ' ' + (unit==='kg'?i18n.kg:unit);
    const update = () => {
      const values = ['gross','tare','discount','price'].map(name => {
        const input = document.getElementById('id_'+name);return input.value === '' ? NaN : Number(input.value.replace(',','.'));
      });
      const [gross,tare,discount,price] = values;
      const valid = values.every(Number.isFinite) && gross>=tare && tare>=0 && discount>=0 && discount<=100 && price>=0;
      const net = gross-tare, clean = net*(1-discount/100);
      [['net',net,'kg'],['clean',clean,'kg'],['amount',clean*price,'UZS']].forEach(([id,value,unit]) => document.getElementById('calc-'+id).textContent = valid ? format(value,unit) : '—');
    };
    calculation.addEventListener('input',update);update();
  }
  const colors = ['#217d5f','#5fa987','#a0c7ae','#d2e5d6','#ebdcb8'];
  const donut = document.getElementById('expense-chart');
  if (donut) {
    const data = JSON.parse(document.getElementById('expense-data').textContent);
    const total = data.reduce((sum, item) => sum + item.value, 0);let accumulated = 0;
    if (total > 0) donut.style.background = 'conic-gradient(' + data.map((item,i) => {
      const start = accumulated;accumulated += item.value/total*100;
      return `${colors[i%colors.length]} ${start}% ${accumulated}%`;
    }).join(',') + ')';
    donut.setAttribute('aria-label',data.map(item=>item.label+': '+Math.round(total ? item.value/total*100 : 0)+'%').join(', '));
  }
  const chart = document.getElementById('cash-chart');
  if (chart) {
    const data = JSON.parse(document.getElementById('cash-data').textContent);
    if (!data.length) {const empty=document.createElement('div');empty.className='empty-state';empty.textContent=i18n.emptyChart;chart.append(empty);return;}
    const NS='http://www.w3.org/2000/svg';
    const el=(tag,attrs,text)=>{const node=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,value));if(text!==undefined)node.textContent=text;return node;};
    const drawChart = () => {
    const width=Math.max(260,chart.clientWidth),height=240,left=48,right=18,top=15,bottom=32;
    const svg=el('svg',{viewBox:`0 0 ${width} ${height}`,preserveAspectRatio:'none'});
    const maximum=Math.max(1,...data.flatMap(item=>[item.income,item.expense]));
    const scale=Math.pow(10,Math.floor(Math.log10(maximum)));const ceiling=Math.ceil(maximum/scale*2)/2*scale;
    const x=i=>left+i*(width-left-right)/Math.max(1,data.length-1);
    const y=value=>height-bottom-value/ceiling*(height-top-bottom);
    const defs=el('defs',{}),gradient=el('linearGradient',{id:'cash-fill',x1:0,y1:0,x2:0,y2:1});
    gradient.append(el('stop',{offset:'0%','stop-color':'#36a57a','stop-opacity':'.18'}),el('stop',{offset:'100%','stop-color':'#36a57a','stop-opacity':'.015'}));defs.append(gradient);svg.append(defs);
    for(let i=0;i<=4;i++) {const value=ceiling*i/4;svg.append(el('line',{x1:left,x2:width-right,y1:y(value),y2:y(value),stroke:'#e9efeb','stroke-dasharray':'3 4'}),el('text',{x:left-12,y:y(value)+3,'text-anchor':'end',fill:'#4c6353','font-size':'12','font-family':'inherit'},new Intl.NumberFormat(i18n.numberLocale,{maximumFractionDigits:0}).format(value/1e6)));}
    const points=key=>data.map((item,i)=>`${x(i)},${y(item[key])}`);
    const income=points('income');svg.append(el('path',{d:`M${left},${height-bottom} L${income.join(' L')} L${x(data.length-1)},${height-bottom} Z`,fill:'url(#cash-fill)'}));
    svg.append(el('polyline',{points:points('expense').join(' '),fill:'none',stroke:'#738d7b','stroke-width':2,'stroke-dasharray':'5 5','stroke-linejoin':'round'}));
    svg.append(el('polyline',{points:income.join(' '),fill:'none',stroke:'#2d9d73','stroke-width':2.5,'stroke-linejoin':'round'}));
    const tooltip=document.createElement('div');tooltip.className='chart-tooltip';tooltip.hidden=true;
    data.forEach((item,i)=>{
      const month=i18n.months[Number(item.label.slice(0,2))-1];
      const step=Math.max(1,Math.ceil(data.length/Math.max(2,Math.floor((width-left-right)/75))));
      if(i===0 || i===data.length-1 || (i%step===0 && i<data.length-step)) svg.append(el('text',{x:x(i),y:height-9,'text-anchor':i===0?'start':i===data.length-1?'end':'middle',fill:'#4c6353','font-size':12},month+' '+item.label.slice(-2)));
      svg.append(el('circle',{cx:x(i),cy:y(item.income),r:3,fill:'#fff',stroke:'#2d9d73','stroke-width':2}));
      const hit=el('rect',{x:x(i)-22,y:0,width:44,height:height-bottom,fill:'transparent',tabindex:0,role:'button','aria-label':`${item.label}: ${i18n.income} ${item.income} UZS, ${i18n.expense} ${item.expense} UZS`});
      const show=()=>{tooltip.hidden=false;tooltip.textContent=`${item.label}\n${i18n.income}: ${new Intl.NumberFormat(i18n.numberLocale).format(item.income)} UZS\n${i18n.expense}: ${new Intl.NumberFormat(i18n.numberLocale).format(item.expense)} UZS`;tooltip.style.left=Math.min(x(i)/width*chart.clientWidth,Math.max(0,chart.clientWidth-240))+'px';tooltip.style.top='3px';};
      hit.addEventListener('mouseenter',show);hit.addEventListener('focus',show);hit.addEventListener('mouseleave',()=>tooltip.hidden=true);hit.addEventListener('blur',()=>tooltip.hidden=true);svg.append(hit);
    });
    chart.replaceChildren(svg,tooltip);
    };
    let lastWidth=0;
    const resize=new ResizeObserver(() => {if(chart.clientWidth!==lastWidth){lastWidth=chart.clientWidth;drawChart();}});
    resize.observe(chart);
  }
});
