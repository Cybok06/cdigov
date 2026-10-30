'use strict';
(() => {
  const app = window.CDIGOV, consent = document.getElementById('location-consent');
  const share = document.getElementById('share-location'), confirm = document.getElementById('confirm-location');
  const message = document.getElementById('location-status'), preview = document.getElementById('location-preview');
  let position, map, marker, circle;
  if (app.locationSaved()) message.textContent = 'Your location has been securely saved to your registration draft.';
  consent.addEventListener('change', () => { if (!consent.checked) {position = null; preview.hidden = true;} });
  share.addEventListener('click',async () => {
    if (!consent.checked) { message.textContent = 'Tick the immediate-storage consent box before requesting your location.'; consent.focus(); return; }
    if (!navigator.geolocation) {message.textContent = 'Your browser does not support location sharing. You can continue without it.';return;}
    if (!window.isSecureContext) {message.textContent = 'Location sharing requires HTTPS or localhost. You can continue without sharing.';return;}
    share.disabled = true; position = null; preview.hidden = true; message.textContent = 'Preparing your draft…';
    try { await app.ensureDraft(); } catch (exc) {message.textContent = exc.message;share.disabled=false;return;}
    if (!consent.checked) {share.disabled=false;return;}
    message.textContent = 'Waiting for your browser’s location permission…';
    navigator.geolocation.getCurrentPosition(result => {
      share.disabled=false;
      if (!consent.checked) {message.textContent='Location was not saved because consent was withdrawn.';return;}
      position = {latitude:result.coords.latitude,longitude:result.coords.longitude,accuracy_meters:result.coords.accuracy,captured_at:new Date(result.timestamp).toISOString()};
      preview.hidden = false; confirm.disabled=false; confirm.textContent='Confirm marker & save location';
      document.getElementById('location-coordinates').textContent = `Latitude ${position.latitude.toFixed(6)} · Longitude ${position.longitude.toFixed(6)} · Reported accuracy ±${Math.round(position.accuracy_meters)} m`;
      document.getElementById('location-accuracy').textContent = position.accuracy_meters > 100 ? 'Low reported accuracy. This location may be over 100 metres from your position. Retry voluntarily, continue without it, or confirm this estimate.' : 'This is your browser’s reported estimate, not a guaranteed exact location. Confirm the marker to save it.';
      message.textContent = 'Location captured. Review the marker below. These coordinates have not yet been saved.';
      if (!window.L) {message.textContent += ' The map could not load. Retry when map access is available.';confirm.disabled=true;return;}
      if (!map) { map = L.map('location-map'); L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',maxZoom:19}).addTo(map); }
      const point = [position.latitude,position.longitude];
      map.setView(point,15); if (marker) map.removeLayer(marker); if (circle) map.removeLayer(circle);
      marker=L.marker(point,{icon:L.icon({iconUrl:'/static/images/map-marker.svg',iconSize:[30,42],iconAnchor:[15,42],popupAnchor:[0,-36]})}).addTo(map).bindPopup('Your reported current location').openPopup();
      circle=L.circle(point,{radius:position.accuracy_meters,color:'#2563eb',fillOpacity:.1}).addTo(map);
      setTimeout(() => map.invalidateSize(),100);
    },err => {
      share.disabled=false;
      message.textContent = ({1:'Location permission was declined. Allow location access in your browser settings, then try again.',2:'Your position is unavailable. Try again when location is available.',3:'The location request timed out. Try again.'})[err.code] || 'Location capture failed. Try again.';
    },{enableHighAccuracy:true,timeout:20000,maximumAge:0});
  });
  confirm.addEventListener('click',async () => {
    if (!position || !consent.checked) {message.textContent='Consent and a captured location are required before saving.';return;}
    confirm.disabled=true; share.disabled=true; message.textContent='Securely saving your location…';
    try {
      const result = await app.api('/api/registration/location',{...position,draft_token:app.token(),consent:true,confirmed:true});
      app.markLocationSaved(); message.textContent=result.message; confirm.textContent='Location saved';
    } catch (exc) {message.textContent=exc.message; confirm.disabled=false;} finally {share.disabled=false;}
  });
})();
