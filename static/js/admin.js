'use strict';
window.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('chart-data');
  if (dataElement && window.Chart) {
    const data = JSON.parse(dataElement.textContent);
    Chart.defaults.font.family = "'Segoe UI', Arial, sans-serif";
    Chart.defaults.font.size = 10; Chart.defaults.color='#8a9bad';
    new Chart(document.getElementById('activity-chart'),{type:'line',data:{labels:data.labels,datasets:[
      {label:'Page views',data:data.visits,borderColor:'#2563eb',backgroundColor:'#2563eb0b',fill:true,tension:.3,pointRadius:1,borderWidth:2},
      {label:'Started',data:data.started,borderColor:'#d4a437',tension:.3,pointRadius:1,borderWidth:2},
      {label:'Submitted',data:data.submitted,borderColor:'#47957b',tension:.3,pointRadius:1,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom',labels:{usePointStyle:true,boxWidth:6,padding:18}}},scales:{x:{grid:{display:false},ticks:{maxTicksLimit:7}},y:{beginAtZero:true,ticks:{precision:0},grid:{color:'#eef2f7'}}}}});
    new Chart(document.getElementById('completion-chart'),{type:'doughnut',data:{labels:['Submitted','Incomplete'],datasets:[{data:[data.complete,data.incomplete],backgroundColor:['#2563eb','#e9eef6'],borderWidth:0,hoverOffset:2}]},options:{responsive:true,maintainAspectRatio:false,cutout:'78%',plugins:{legend:{position:'bottom',labels:{usePointStyle:true,boxWidth:6,padding:20}}}}});
  }
  const mapButton = document.getElementById('open-record-map');
  if (mapButton) mapButton.addEventListener('click', () => {
    if (!window.L) {mapButton.textContent='Map could not load. Refresh and try again.';return;}
    const panel = document.getElementById('admin-map'); panel.hidden=false;
    const point = [Number(mapButton.dataset.lat),Number(mapButton.dataset.lng)];
    const map = L.map(panel).setView(point,15);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:19}).addTo(map);
    L.marker(point,{icon:L.icon({iconUrl:'/static/images/map-marker.svg',iconSize:[30,42],iconAnchor:[15,42],popupAnchor:[0,-36]})}).addTo(map).bindPopup('Confirmed browser estimate').openPopup();
    L.circle(point,{radius:Number(mapButton.dataset.accuracy),color:'#2563eb',fillOpacity:.1}).addTo(map);
    mapButton.disabled=true;
  },{once:true});
  document.querySelectorAll('.delete-record-form').forEach(form => form.addEventListener('submit',event => {if (!window.confirm('Permanently delete this registration and its saved information?')) event.preventDefault();}));
});
