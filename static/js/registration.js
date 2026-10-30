'use strict';
(() => {
  const initial = JSON.parse(document.getElementById('initial-data').textContent);
  const form = document.getElementById('registration-form');
  const error = document.getElementById('form-error');
  const status = document.getElementById('save-status');
  const steps = [...document.querySelectorAll('.form-step')];
  let currentStep = 0, draftToken = initial.draft_token, saveQueue = Promise.resolve(), pendingTimer, dirty = false;
  let locationSaved = initial.location_saved, photoSaved = initial.photo_saved;
  const fields = [...form.querySelectorAll('[name]')];
  fields.forEach(input => { if (initial[input.name] !== undefined) input.value = String(initial[input.name]); });
  document.getElementById('date_of_birth').max = new Date().toISOString().slice(0, 10);
  document.getElementById('photo-status').textContent = photoSaved ? 'Your previously uploaded photograph is saved.' : 'A clear photograph of yourself (optional).';
  function showError(message) { error.textContent = message; error.hidden = false; error.scrollIntoView({block:'center',behavior:'smooth'}); }
  function values() { const result = Object.fromEntries(fields.map(input => [input.name, input.value])); result.dual_citizenship = result.dual_citizenship === 'true'; return result; }
  async function api(path, data, multipart = false) {
    let response;
    try {
      response = await fetch(path, {method:'POST', credentials:'same-origin', headers:{'X-CSRFToken':document.querySelector('meta[name="csrf-token"]').content, ...(multipart ? {} : {'Content-Type':'application/json'})}, body:multipart ? data : JSON.stringify(data)});
    } catch (_) { throw new Error('Connection interrupted. Your latest changes may not be saved. Check your connection and try again.'); }
    let result;
    try { result = await response.json(); } catch (_) { throw new Error('We could not complete this request. Refresh the page and try again.'); }
    if (!response.ok) throw new Error(result.error || 'Your changes could not be saved. Try again.');
    return result;
  }
  function save(force = false) {
    clearTimeout(pendingTimer);
    const snapshot = values();
    if (!force && !draftToken && (!snapshot.surname.trim() || !snapshot.first_names.trim())) return Promise.resolve();
    status.textContent = 'Saving…';
    const task = saveQueue.catch(() => {}).then(async () => {
      const result = await api('/api/registration/draft', {...snapshot, ...(draftToken ? {draft_token:draftToken} : {})});
      draftToken = result.draft_token;
      dirty = JSON.stringify(snapshot) !== JSON.stringify(values());
      status.textContent = dirty ? 'Changes waiting to save' : 'All changes saved';
      return draftToken;
    });
    saveQueue = task;
    return task.catch(exc => { status.textContent = 'Not saved · retry'; throw exc; });
  }
  function nationalityVisibility() {
    const enabled = document.getElementById('dual_citizenship').value === 'true';
    document.getElementById('second-nationality-wrap').hidden = !enabled;
    document.getElementById('second_nationality').required = enabled;
    if (!enabled) document.getElementById('second_nationality').value = '';
  }
  nationalityVisibility();
  form.addEventListener('input', event => {
    if (!event.target.name) return;
    dirty = true; status.textContent = 'Unsaved changes';
    nationalityVisibility();
    clearTimeout(pendingTimer);
    pendingTimer = setTimeout(() => save().catch(exc => showError(exc.message)), 700);
  });
  function validateStep() {
    for (const input of steps[currentStep].querySelectorAll('input[name],select[name],textarea[name]')) {
      if (!input.checkValidity()) { input.reportValidity(); return false; }
    }
    return true;
  }
  const labels = ['Personal information', 'Place of birth', 'Residential information', 'Parental information'];
  function renderReview() {
    const root = document.getElementById('review-information'); root.replaceChildren();
    steps.slice(0,4).forEach((step, index) => {
      const section = document.createElement('section'); section.className = 'review-section';
      const heading = document.createElement('h3'); heading.textContent = labels[index]; section.append(heading);
      const grid = document.createElement('dl'); grid.className = 'review-grid';
      step.querySelectorAll('[name]').forEach(input => {
        if (input.name === 'second_nationality' && document.getElementById('dual_citizenship').value !== 'true') return;
        const wrap = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
        dt.textContent = input.labels[0].textContent.replace('*','').trim();
        dd.textContent = input.name === 'dual_citizenship' ? (input.value === 'true' ? 'Yes' : 'No') : input.value || 'Not supplied';
        wrap.append(dt, dd); grid.append(wrap);
      });
      section.append(grid); root.append(section);
    });
    const details = document.createElement('p'); details.className = 'small mt-3';
    details.textContent = `Photograph: ${photoSaved ? 'saved' : 'not supplied'}. Location: ${locationSaved ? 'saved to this draft' : 'not shared'}.`;
    root.append(details);
  }
  function showStep(index) {
    currentStep = index;
    steps.forEach((step,i) => step.hidden = i !== index);
    document.querySelectorAll('[data-step-indicator]').forEach((item,i) => {item.classList.toggle('active',i === index); item.classList.toggle('done',i < index); if (i === index) item.setAttribute('aria-current','step'); else item.removeAttribute('aria-current');});
    document.getElementById('step-count').textContent = `STEP ${index + 1} OF 5`;
    document.getElementById('form-progress').style.width = `${(index + 1)*20}%`;
    document.getElementById('previous-step').hidden = index === 0;
    document.getElementById('next-step').hidden = index === 4;
    document.getElementById('submit-registration').hidden = index !== 4;
    if (index === 4) renderReview();
    steps[index].querySelector('h2').setAttribute('tabindex','-1');
    steps[index].querySelector('h2').focus({preventScroll:true});
    document.querySelector('.registration-main').scrollIntoView({block:'start',behavior:'smooth'});
  }
  document.getElementById('next-step').addEventListener('click',async event => {
    if (!validateStep()) return;
    if (currentStep === 2 && !locationSaved) {
      const dialog = document.getElementById('location-required-dialog');
      if (dialog && typeof dialog.showModal === 'function') dialog.showModal();
      else showError('Location access and a confirmed location are required to continue.');
      return;
    }
    const button = event.currentTarget; button.disabled = true; error.hidden = true;
    try { await save(true); showStep(currentStep + 1); } catch (exc) { showError(exc.message); } finally {button.disabled = false;}
  });
  document.getElementById('close-location-dialog')?.addEventListener('click', () => document.getElementById('location-required-dialog').close());
  document.getElementById('previous-step').addEventListener('click', () => showStep(currentStep - 1));
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (currentStep !== 4) return;
    if (!document.getElementById('accuracy-confirmed').checked || !document.getElementById('processing-consent').checked) { showError('Confirm that your information is accurate and agree to the privacy notice.'); return; }
    const button = document.getElementById('submit-registration'); button.disabled = true; button.textContent = 'Submitting…'; error.hidden = true;
    try {
      await saveQueue.catch(() => {});
      const result = await api('/api/registration/submit', {...values(), draft_token:draftToken, accuracy_confirmed:true, processing_consent:true});
      dirty = false; window.location.assign(result.redirect);
    } catch (exc) { showError(exc.message); button.disabled = false; button.textContent = 'Submit Registration'; }
  });
  document.getElementById('profile-photo').addEventListener('change',async event => {
    const file = event.target.files[0]; if (!file) return;
    const message = document.getElementById('photo-status');
    const resetPhoto = () => { event.target.value = ''; document.getElementById('photo-preview').innerHTML = '<i class="bi bi-person"></i>'; photoSaved = false; message.textContent = 'No photograph saved. You can continue without one.'; };
    if (file.size > 5*1024*1024) { showError('Choose a photograph smaller than 5 MB. You can continue without a photograph.'); if (window.confirm('This photograph is too large. Continue without a photograph?')) resetPhoto(); return; }
    const img = document.createElement('img'); const objectUrl = URL.createObjectURL(file); img.src = objectUrl; img.alt = 'Preview of your selected photograph'; img.onload = () => URL.revokeObjectURL(objectUrl);
    document.getElementById('photo-preview').replaceChildren(img);
    message.textContent = 'Uploading and converting photograph...';
    try {
      await save(true);
      const data = new FormData(); data.append('photo',file); data.append('draft_token',draftToken);
      await api('/api/registration/photo',data,true);
      img.alt = 'Your uploaded profile photograph'; photoSaved = true; message.textContent = 'Photograph securely saved.';
    } catch (exc) { message.textContent = 'Photograph upload failed.'; showError(`${exc.message} You can continue without a photograph.`); if (window.confirm('The photograph could not be uploaded or converted. Continue without a photograph?')) resetPhoto(); }
  });
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault();event.returnValue='';}});
  window.CDIGOV = {api, ensureDraft:() => save(true), token:() => draftToken, showError, markLocationSaved:() => {locationSaved = true;}, locationSaved:() => locationSaved};
})();
