'use strict';

const state = {
  user: null,
  bootstrap: null,
  catalog: null,
  currentDepartmentId: null,
  step: 0,
  editingId: null,
  evaluation: null,
  recognition: null,
  voiceTarget: null,
  confirmResolver: null,
  baseViewportHeight: 0,
  forcedPasswordChange: false,
  adminData: {departments: [], positions: [], users: []},
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function createClientRecordId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `eval-${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

function isAdmin() { return state.user?.role === 'admin'; }
function finalStep() { return (state.bootstrap?.areas?.length || 5) + 1; }
function totalSteps() { return (state.bootstrap?.areas?.length || 5) + 2; }
function departmentById(id) { return state.bootstrap?.departments?.find(item => Number(item.id) === Number(id)); }
function currentDepartment() { return departmentById(state.currentDepartmentId) || state.catalog?.department || null; }

function emptyAreas() {
  const result = {};
  for (const area of state.bootstrap.areas) {
    result[area.code] = {attitude: null, performance: null, technical: null, has_comment: false, comment: ''};
  }
  return result;
}

function newEvaluation() {
  return {
    evaluation_date: state.bootstrap.today,
    employee_name: '',
    category: '',
    status: 'draft',
    department_id: state.currentDepartmentId,
    client_record_id: createClientRecordId(),
    revision: null,
    areas: emptyAreas(),
  };
}

function toast(message, ms = 3400) {
  const box = $('#toast');
  box.textContent = message;
  box.classList.add('show');
  clearTimeout(box._timer);
  box._timer = setTimeout(() => box.classList.remove('show'), ms);
}

function formatDate(iso) {
  if (!iso) return '—';
  const [year, month, day] = iso.split('-');
  return `${day}/${month}/${year}`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
}

async function api(url, options = {}) {
  const headers = {...(options.headers || {})};
  if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  const response = await fetch(url, {...options, headers, credentials: 'same-origin'});
  if (!response.ok) {
    let message = `Error ${response.status}`;
    try { message = (await response.json()).error || message; } catch (_) {}
    const error = new Error(message);
    error.status = response.status;
    if (response.status === 401 && !url.includes('/api/login')) showLogin(false);
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

function showLogin(clearFields = false) {
  state.user = null;
  state.bootstrap = null;
  state.catalog = null;
  $('#appShell').classList.add('hidden');
  $('#loginScreen').classList.remove('hidden');
  if (clearFields) {
    $('#loginUsername').value = '';
    $('#loginPassword').value = '';
  }
  setTimeout(() => $('#loginUsername').focus(), 80);
}

function showApp() {
  $('#loginScreen').classList.add('hidden');
  $('#appShell').classList.remove('hidden');
}

async function handleLogin(event) {
  event.preventDefault();
  try {
    const result = await api('/api/login', {
      method: 'POST',
      body: JSON.stringify({username: $('#loginUsername').value, password: $('#loginPassword').value}),
    });
    $('#loginPassword').value = '';
    await loadApplication(result.user);
    toast(`Bienvenido, ${result.user.display_name}.`);
  } catch (error) {
    toast(error.message, 4800);
  }
}

async function restoreSession() {
  try {
    const result = await api('/api/session');
    await loadApplication(result.user);
  } catch (_) {
    showLogin(false);
  }
}

async function loadApplication(user, departmentId = null) {
  state.user = user;
  const query = departmentId ? `?department_id=${departmentId}` : '';
  state.bootstrap = await api(`/api/bootstrap${query}`);
  state.user = state.bootstrap.user;
  state.catalog = state.bootstrap.catalog;
  state.currentDepartmentId = state.catalog.department?.id || state.user.department_id || null;

  if (!$('#areaSteps').children.length) renderAreaSteps();
  populateDepartmentSelectors();
  populateCatalogs();
  configureRoleUI();
  updateSessionHeader();
  prepareBlankCapture();
  showApp();

  if (state.user.must_change_password) openPasswordDialog(true);
}

function configureRoleUI() {
  $('#adminTab').classList.toggle('hidden', !isAdmin());
  $('.tabs').classList.toggle('three-tabs', !isAdmin());
  $('#adminDepartmentField').classList.toggle('hidden', !isAdmin());
  $('#fixedDepartmentField').classList.toggle('hidden', isAdmin());
  $$('.admin-only-control').forEach(el => el.classList.toggle('hidden', !isAdmin()));
  $('#adminGlobalExport').classList.toggle('hidden', !isAdmin());
  $('#adminBackupCard').classList.toggle('hidden', !isAdmin());
  $('#exportDepartment').disabled = !isAdmin();
  $('#recordDepartment').disabled = !isAdmin();
  $('#fixedDepartmentName').textContent = state.user.department_name || currentDepartment()?.name || 'Sin departamento';
}

function updateSessionHeader() {
  $('#userBadge').textContent = `${state.user.display_name} · ${isAdmin() ? 'ADMINISTRADOR' : 'CAPTURISTA'}`;
  const dept = currentDepartment();
  $('#departmentBadge').textContent = isAdmin() ? `Vista: ${dept?.name || 'Sin departamento'}` : (state.user.department_name || 'Sin departamento');
  $('#captureContextText').textContent = isAdmin()
    ? `La evaluación se guardará en ${dept?.name || 'el departamento seleccionado'} con su cuenta administradora.`
    : `La evaluación se guardará en ${state.user.department_name} con la cuenta ${state.user.username}.`;
  $('#recordsScopeText').textContent = isAdmin()
    ? 'Puede filtrar por departamento. La base permanece unificada.'
    : `Solo se muestran registros de ${state.user.department_name}.`;
}

function optionsForDepartments(includePlaceholder = false) {
  const options = [];
  if (includePlaceholder) options.push('<option value="">Seleccione un departamento</option>');
  for (const department of state.bootstrap.departments) {
    options.push(`<option value="${department.id}">${escapeHtml(department.name)} (${escapeHtml(department.code)})</option>`);
  }
  return options.join('');
}

function populateDepartmentSelectors() {
  const html = optionsForDepartments(false);
  const htmlPlaceholder = optionsForDepartments(true);
  for (const id of ['captureDepartment', 'recordDepartment', 'exportDepartment']) {
    const element = $(`#${id}`);
    if (!element) continue;
    element.innerHTML = html;
    element.value = String(state.currentDepartmentId || '');
  }
  for (const id of ['positionDepartment', 'positionListDepartment', 'userDepartment']) {
    const element = $(`#${id}`);
    if (!element) continue;
    element.innerHTML = id === 'userDepartment' ? htmlPlaceholder : html;
    if (id !== 'userDepartment') element.value = String(state.currentDepartmentId || '');
  }
}

async function loadCatalog(departmentId, {reset = false} = {}) {
  const catalog = await api(`/api/catalog?department_id=${departmentId}`);
  state.catalog = catalog;
  state.currentDepartmentId = catalog.department?.id || Number(departmentId);
  populateCatalogs();
  updateSessionHeader();
  if (reset) prepareBlankCapture();
}

function renderAreaSteps() {
  $('#areaSteps').innerHTML = state.bootstrap.areas.map((area, index) => {
    const previousLabel = index === 0 ? 'datos generales' : state.bootstrap.areas[index - 1].title;
    return `
    <article class="step" data-step="${index + 1}" data-area="${area.code}">
      <div class="card hero-card area-hero">
        <div>
          <p class="section-kicker">ÁREA ${index + 1} DE ${state.bootstrap.areas.length}</p>
          <h2>${escapeHtml(area.title)}</h2>
          <p>Seleccione 3, 2 o 1. Puede dejar cualquier criterio en blanco y continuar.</p>
        </div>
        <button type="button" class="secondary inline-back" data-go-step="${index}">← Volver a ${escapeHtml(previousLabel)}</button>
      </div>
      <div class="card">
        ${metricHtml(area.code, 'attitude', 'Actitud')}
        ${metricHtml(area.code, 'performance', 'Desempeño')}
        ${metricHtml(area.code, 'technical', 'Conocimiento técnico')}
        <label class="comment-toggle">
          <input type="checkbox" class="has-comment" data-area="${area.code}">
          <span>Esta área tiene comentario u observación</span>
        </label>
        <div class="comment-block hidden" data-comment-block="${area.code}">
          <label for="comment-${area.code}">${escapeHtml(area.comment)}</label>
          <div class="input-with-action">
            <textarea id="comment-${area.code}" data-comment-area="${area.code}" placeholder="Toque y dicte la observación; después puede corregirla"></textarea>
            <button class="mic-btn" type="button" data-voice-target="comment-${area.code}" aria-label="Dictar observación">🎙</button>
          </div>
        </div>
      </div>
    </article>`;
  }).join('');
}

function metricHtml(areaCode, field, label) {
  return `<div class="metric" data-metric="${areaCode}.${field}">
    <h3>${label}</h3>
    <div class="score-row">
      <button type="button" class="score-btn" data-area="${areaCode}" data-field="${field}" data-score="3">3</button>
      <button type="button" class="score-btn" data-area="${areaCode}" data-field="${field}" data-score="2">2</button>
      <button type="button" class="score-btn" data-area="${areaCode}" data-field="${field}" data-score="1">1</button>
      <button type="button" class="score-btn" data-area="${areaCode}" data-field="${field}" data-score="">—</button>
    </div>
  </div>`;
}

function populateCatalogs() {
  const categories = state.catalog?.categories || [];
  const employees = state.catalog?.employees || [];
  $('#category').innerHTML = '<option value="">Seleccione un puesto</option>' + categories.map(c => `<option>${escapeHtml(c)}</option>`).join('');
  $('#employeeList').innerHTML = employees.map(e => `<option value="${escapeHtml(e.display_name)}" data-category="${escapeHtml(e.last_category || '')}"></option>`).join('');
  $('#captureDepartment').value = String(state.currentDepartmentId || '');
  if (!state.editingId) $('#category').value = state.evaluation?.category || '';
}

function bindEvents() {
  $('#loginForm').addEventListener('submit', handleLogin);
  $('#logoutBtn').addEventListener('click', logout);
  $('#openPasswordBtn').addEventListener('click', () => openPasswordDialog(false));
  $('#passwordForm').addEventListener('submit', changeOwnPassword);
  $('#passwordCancel').addEventListener('click', closePasswordDialog);
  $('#resetPasswordForm').addEventListener('submit', resetUserPassword);
  $('#resetPasswordCancel').addEventListener('click', () => $('#resetPasswordDialog').classList.add('hidden'));

  $$('.tab').forEach(button => button.addEventListener('click', () => switchView(button.dataset.view)));
  $('#prevBtn').addEventListener('click', () => changeStep(state.step - 1));
  $('#nextBtn').addEventListener('click', () => changeStep(state.step + 1));
  $('#skipBtn').addEventListener('click', () => changeStep(Math.min(state.step + 1, finalStep())));
  $('#saveDraftBtn').addEventListener('click', () => saveEvaluation('draft'));
  $('#finishBtn').addEventListener('click', () => saveEvaluation('final'));
  $('#newEvaluationBtn').addEventListener('click', resetCapture);
  $('#refreshRecords').addEventListener('click', loadRecords);
  $('#recordSearch').addEventListener('input', debounce(loadRecords, 250));
  $('#recordStatus').addEventListener('change', loadRecords);
  $('#recordDepartment').addEventListener('change', loadRecords);
  $('#recordsList').addEventListener('click', handleRecordAction);
  $('#reviewContent').addEventListener('click', handleReviewAction);
  $('#downloadExcel').addEventListener('click', downloadExcel);
  $('#downloadAllExcel').addEventListener('click', downloadAllExcel);
  $('#downloadDepartmentsZip').addEventListener('click', () => { window.location.href = '/export/departamentos.zip'; });
  $('#downloadBackup').addEventListener('click', () => { window.location.href = '/backup/operativo.zip'; });

  $('#evaluationDate').addEventListener('change', syncGeneralFromForm);
  $('#employeeName').addEventListener('input', syncGeneralFromForm);
  $('#category').addEventListener('change', syncGeneralFromForm);
  $('#employeeName').addEventListener('change', autofillCategoryFromEmployee);
  $('#employeeName').addEventListener('click', () => startVoice('employeeName', false));
  $('#captureDepartment').addEventListener('change', handleCaptureDepartmentChange);
  $('#areaSteps').addEventListener('click', handleAreaClick);
  $('#areaSteps').addEventListener('change', handleAreaChange);
  $('#areaSteps').addEventListener('input', handleAreaInput);

  $('#departmentForm').addEventListener('submit', createDepartment);
  $('#positionForm').addEventListener('submit', createPosition);
  $('#positionListDepartment').addEventListener('change', renderAdminPositions);
  $('#userForm').addEventListener('submit', createCapturist);
  $('#departmentsAdminList').addEventListener('click', handleAdminAction);
  $('#positionsAdminList').addEventListener('click', handleAdminAction);
  $('#usersAdminList').addEventListener('click', handleAdminAction);

  document.addEventListener('click', event => {
    const go = event.target.closest('[data-go-step]');
    if (go) {
      changeStep(Number(go.dataset.goStep));
      return;
    }
    const mic = event.target.closest('[data-voice-target]');
    if (mic) startVoice(mic.dataset.voiceTarget, mic.dataset.voiceTarget.startsWith('comment-'));
  });
  $('#confirmCancel').addEventListener('click', () => resolveConfirm(false));
  $('#confirmAccept').addEventListener('click', () => resolveConfirm(true));
  setupKeyboardAwareActions();
}

async function logout() {
  try { await api('/api/logout', {method: 'POST'}); } catch (_) {}
  showLogin(true);
  toast('Sesión cerrada.');
}

function switchView(name) {
  if (name === 'admin' && !isAdmin()) return;
  $$('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === name));
  $$('.view').forEach(v => v.classList.remove('active'));
  $(`#${name}View`).classList.add('active');
  if (name === 'records') loadRecords();
  if (name === 'admin') loadAdminData();
}

async function handleCaptureDepartmentChange() {
  if (!isAdmin()) return;
  const departmentId = Number($('#captureDepartment').value);
  if (!departmentId || departmentId === Number(state.currentDepartmentId)) return;
  const hasData = Boolean(state.evaluation?.employee_name || state.evaluation?.category || Object.values(state.evaluation?.areas || {}).some(a => a.attitude || a.performance || a.technical || a.comment));
  if (hasData) {
    const accepted = await confirmAction('Cambiar departamento', 'Se limpiará la captura actual para cargar los puestos del nuevo departamento.');
    if (!accepted) {
      $('#captureDepartment').value = String(state.currentDepartmentId);
      return;
    }
  }
  try {
    await loadCatalog(departmentId, {reset: true});
    synchronizeDepartmentSelectors(departmentId);
    toast(`Departamento cambiado a ${currentDepartment()?.name}.`);
  } catch (error) { toast(error.message); }
}

function synchronizeDepartmentSelectors(departmentId) {
  for (const id of ['captureDepartment', 'recordDepartment', 'exportDepartment', 'positionDepartment', 'positionListDepartment']) {
    const element = $(`#${id}`);
    if (element && [...element.options].some(o => Number(o.value) === Number(departmentId))) element.value = String(departmentId);
  }
}

function syncGeneralFromForm() {
  if (!state.evaluation) return;
  state.evaluation.evaluation_date = $('#evaluationDate').value;
  state.evaluation.employee_name = $('#employeeName').value.trim();
  state.evaluation.category = $('#category').value;
  state.evaluation.department_id = state.currentDepartmentId;
  $('#dateHuman').textContent = formatDate(state.evaluation.evaluation_date);
}

function autofillCategoryFromEmployee() {
  const current = $('#employeeName').value.trim().toLocaleLowerCase('es-MX');
  const employee = (state.catalog.employees || []).find(e => e.display_name.toLocaleLowerCase('es-MX') === current);
  if (employee?.last_category && !$('#category').value && (state.catalog.categories || []).includes(employee.last_category)) {
    $('#category').value = employee.last_category;
    syncGeneralFromForm();
    toast('Puesto recuperado del historial de este departamento.');
  }
}

function handleAreaClick(event) {
  const score = event.target.closest('.score-btn');
  if (!score || !state.evaluation) return;
  const value = score.dataset.score === '' ? null : Number(score.dataset.score);
  state.evaluation.areas[score.dataset.area][score.dataset.field] = value;
  const metric = score.closest('.metric');
  $$('.score-btn', metric).forEach(btn => btn.classList.toggle('selected', btn === score));
}

function handleAreaChange(event) {
  if (!event.target.matches('.has-comment')) return;
  const area = event.target.dataset.area;
  const checked = event.target.checked;
  state.evaluation.areas[area].has_comment = checked;
  const block = $(`[data-comment-block="${area}"]`);
  block.classList.toggle('hidden', !checked);
  if (!checked) {
    state.evaluation.areas[area].comment = '';
    $(`#comment-${area}`).value = '';
  } else {
    setTimeout(() => startVoice(`comment-${area}`, true), 80);
  }
}

function handleAreaInput(event) {
  if (!event.target.matches('[data-comment-area]')) return;
  state.evaluation.areas[event.target.dataset.commentArea].comment = event.target.value;
}

function changeStep(next) {
  syncGeneralFromForm();
  if (next > 0 && !state.evaluation.evaluation_date) {
    toast('Seleccione la fecha para continuar.');
    return;
  }
  state.step = Math.max(0, Math.min(finalStep(), next));
  $$('.step').forEach(step => step.classList.toggle('active', Number(step.dataset.step) === state.step));
  const labels = ['Datos generales', ...state.bootstrap.areas.map(a => a.title), 'Revisión final'];
  $('#stepLabel').textContent = labels[state.step];
  $('#stepCounter').textContent = `${state.step + 1} de ${totalSteps()}`;
  $('#progressBar').style.width = `${((state.step + 1) / totalSteps()) * 100}%`;
  $('#prevBtn').disabled = state.step === 0;
  $('#nextBtn').classList.toggle('hidden', state.step === finalStep());
  $('#skipBtn').classList.toggle('hidden', state.step === 0 || state.step === finalStep());
  $('#finishBtn').classList.toggle('hidden', state.step !== finalStep());
  if (state.step === finalStep()) renderReview();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function renderReview() {
  syncGeneralFromForm();
  const scores = [];
  for (const area of state.bootstrap.areas) {
    for (const field of ['attitude', 'performance', 'technical']) {
      const value = state.evaluation.areas[area.code][field];
      if (value !== null) scores.push(value);
    }
  }
  const average = scores.length ? (scores.reduce((a,b) => a+b, 0) / scores.length).toFixed(2) : '—';
  const department = currentDepartment();
  $('#reviewContent').innerHTML = `
    <div class="review-section-title">
      <h3>Datos generales</h3>
      <button type="button" class="secondary compact" data-review-step="0">Editar datos</button>
    </div>
    <div class="review-grid">
      <div class="review-item"><strong>Departamento</strong>${escapeHtml(department?.name || 'Pendiente')}</div>
      <div class="review-item"><strong>Fecha</strong>${escapeHtml(formatDate(state.evaluation.evaluation_date))}</div>
      <div class="review-item"><strong>Nombre</strong>${escapeHtml(state.evaluation.employee_name || 'Pendiente')}</div>
      <div class="review-item"><strong>Categoría</strong>${escapeHtml(state.evaluation.category || 'Pendiente')}</div>
      <div class="review-item"><strong>Promedio general</strong>${average}</div>
      <div class="review-item"><strong>Capturista</strong>${escapeHtml(state.user.display_name)}</div>
    </div>
    ${state.bootstrap.areas.map((area, index) => {
      const r = state.evaluation.areas[area.code];
      return `<div class="review-area">
        <div class="review-area-header">
          <h4>${escapeHtml(area.title)}</h4>
          <button type="button" class="secondary compact" data-review-step="${index + 1}">Editar esta área</button>
        </div>
        <div>Actitud: <strong>${r.attitude ?? '—'}</strong> · Desempeño: <strong>${r.performance ?? '—'}</strong> · Conoc. técnico: <strong>${r.technical ?? '—'}</strong></div>
        <div><strong>Observación:</strong> ${escapeHtml(r.has_comment && r.comment ? r.comment : 'Sin observación')}</div>
      </div>`;
    }).join('')}`;
}

function handleReviewAction(event) {
  const button = event.target.closest('[data-review-step]');
  if (!button) return;
  changeStep(Number(button.dataset.reviewStep));
  toast('Sección abierta para corregir.');
}

function hydrateForm() {
  $('#evaluationDate').value = state.evaluation.evaluation_date || state.bootstrap.today;
  $('#employeeName').value = state.evaluation.employee_name || '';
  $('#category').value = state.evaluation.category || '';
  $('#captureDepartment').value = String(state.currentDepartmentId || '');
  $('#captureDepartment').disabled = Boolean(state.editingId);
  $('#dateHuman').textContent = formatDate($('#evaluationDate').value);
  for (const area of state.bootstrap.areas) {
    const data = state.evaluation.areas[area.code];
    for (const field of ['attitude', 'performance', 'technical']) {
      const metric = $(`[data-metric="${area.code}.${field}"]`);
      $$('.score-btn', metric).forEach(btn => {
        const buttonValue = btn.dataset.score === '' ? null : Number(btn.dataset.score);
        btn.classList.toggle('selected', buttonValue === data[field]);
      });
    }
    const check = $(`.has-comment[data-area="${area.code}"]`);
    check.checked = Boolean(data.has_comment);
    $(`[data-comment-block="${area.code}"]`).classList.toggle('hidden', !data.has_comment);
    $(`#comment-${area.code}`).value = data.comment || '';
  }
}

function prepareBlankCapture() {
  state.editingId = null;
  state.evaluation = newEvaluation();
  state.step = 0;
  hydrateForm();
  changeStep(0);
}

function resetCapture() {
  prepareBlankCapture();
  switchView('capture');
  toast(`Nueva evaluación lista en ${currentDepartment()?.name || 'el departamento actual'}.`);
}

async function saveEvaluation(status) {
  syncGeneralFromForm();
  state.evaluation.status = status;
  try {
    const url = state.editingId ? `/api/evaluations/${state.editingId}` : '/api/evaluations';
    const method = state.editingId ? 'PUT' : 'POST';
    const saved = await api(url, {method, body: JSON.stringify(state.evaluation)});
    refreshEmployeeCatalog(saved);
    if (status === 'final') {
      prepareBlankCapture();
      switchView('records');
      toast('Evaluación final guardada. El formulario quedó limpio para la siguiente persona.');
    } else {
      state.editingId = saved.id;
      state.evaluation = saved;
      hydrateForm();
      toast('Borrador guardado en la base general.');
    }
  } catch (error) {
    toast(error.status === 409 ? `${error.message} Sus datos locales no se borraron.` : error.message, 6500);
  }
}

function refreshEmployeeCatalog(saved) {
  if (!saved.employee_name || Number(saved.department_id) !== Number(state.currentDepartmentId)) return;
  const employees = state.catalog.employees;
  const found = employees.find(e => e.display_name.toLocaleLowerCase('es-MX') === saved.employee_name.toLocaleLowerCase('es-MX'));
  if (found) found.last_category = saved.category;
  else employees.push({display_name: saved.employee_name, last_category: saved.category});
  populateCatalogs();
}

function recordsDepartmentId() {
  return isAdmin() ? Number($('#recordDepartment').value || state.currentDepartmentId) : Number(state.user.department_id);
}

async function loadRecords() {
  if (!state.user) return;
  const params = new URLSearchParams();
  if ($('#recordSearch').value.trim()) params.set('q', $('#recordSearch').value.trim());
  if ($('#recordStatus').value) params.set('status', $('#recordStatus').value);
  params.set('department_id', recordsDepartmentId());
  try {
    const data = await api(`/api/evaluations?${params}`);
    renderStats(data.stats);
    renderRecords(data.items);
  } catch (error) { toast(error.message); }
}

function renderStats(stats) {
  const operatorTotal = Object.values(stats.by_operator || {}).reduce((a, b) => a + b, 0);
  $('#statsGrid').innerHTML = [
    ['Total', stats.total], ['Finales', stats.final], ['Borradores', stats.drafts], ['Personal', stats.employees], ['Capturas identificadas', operatorTotal]
  ].map(([label, value]) => `<div class="stat"><strong>${value}</strong><span>${label}</span></div>`).join('');
}

function renderRecords(items) {
  const list = $('#recordsList');
  if (!items.length) {
    list.innerHTML = '<div class="card empty">Todavía no hay evaluaciones con esos filtros.</div>';
    return;
  }
  list.innerHTML = items.map(item => `
    <article class="record">
      <div>
        <div class="record-badges">
          <span class="badge ${item.status}">${item.status === 'final' ? 'FINAL' : 'BORRADOR'}</span>
          <span class="badge department">${escapeHtml(item.department_name || 'Sin departamento')}</span>
          <span class="badge operator">${escapeHtml(item.captured_by_name || item.operator_code || 'Sin capturista')}</span>
          <span class="badge revision">v${escapeHtml(item.revision || 1)}</span>
        </div>
        <h3>${escapeHtml(item.employee_name || 'Sin nombre')}</h3>
        <p>${escapeHtml(item.category || 'Sin categoría')}</p>
        <p>${formatDate(item.evaluation_date)} · Promedio: <strong>${item.average ?? '—'}</strong></p>
      </div>
      <div class="record-actions">
        <button type="button" class="secondary" data-record-action="edit" data-record-id="${item.id}">Editar</button>
        ${isAdmin() ? `<button type="button" class="danger" data-record-action="delete" data-record-id="${item.id}" data-record-name="${escapeHtml(item.employee_name || 'este registro')}">Eliminar</button>` : ''}
      </div>
    </article>`).join('');
}

async function editEvaluation(id) {
  try {
    const evaluation = await api(`/api/evaluations/${id}`);
    if (Number(evaluation.department_id) !== Number(state.currentDepartmentId)) {
      await loadCatalog(Number(evaluation.department_id));
      synchronizeDepartmentSelectors(evaluation.department_id);
    }
    state.evaluation = evaluation;
    state.editingId = id;
    hydrateForm();
    changeStep(0);
    switchView('capture');
    toast(`Registro cargado para edición en ${evaluation.department_name}.`);
  } catch (error) { toast(error.message); }
}

async function deleteEvaluation(id, name) {
  const accepted = await confirmAction('Eliminar evaluación', `Se eliminará la evaluación de ${name}. Esta acción no se puede deshacer.`);
  if (!accepted) return;
  try {
    await api(`/api/evaluations/${id}`, {method: 'DELETE'});
    toast('Evaluación eliminada.');
    loadRecords();
  } catch (error) { toast(error.message); }
}

function handleRecordAction(event) {
  const button = event.target.closest('[data-record-action]');
  if (!button) return;
  const id = Number(button.dataset.recordId);
  if (button.dataset.recordAction === 'edit') editEvaluation(id);
  if (button.dataset.recordAction === 'delete') deleteEvaluation(id, button.dataset.recordName || 'este registro');
}

function exportDepartmentId() {
  return isAdmin() ? Number($('#exportDepartment').value || state.currentDepartmentId) : Number(state.user.department_id);
}

function downloadExcel() {
  const params = new URLSearchParams({status: $('#exportStatus').value, department_id: exportDepartmentId()});
  if ($('#exportStart').value) params.set('start', $('#exportStart').value);
  if ($('#exportEnd').value) params.set('end', $('#exportEnd').value);
  window.location.href = `/export/evaluaciones.xlsx?${params}`;
}

function downloadAllExcel() {
  window.location.href = `/export/evaluaciones.xlsx?status=all&department_id=${exportDepartmentId()}`;
}

function confirmAction(title, message) {
  $('#confirmTitle').textContent = title;
  $('#confirmMessage').textContent = message;
  $('#confirmDialog').classList.remove('hidden');
  return new Promise(resolve => { state.confirmResolver = resolve; });
}

function resolveConfirm(value) {
  $('#confirmDialog').classList.add('hidden');
  if (state.confirmResolver) state.confirmResolver(value);
  state.confirmResolver = null;
}

function openPasswordDialog(forced) {
  state.forcedPasswordChange = forced;
  $('#passwordTitle').textContent = forced ? 'Cambie la contraseña inicial' : 'Cambiar contraseña';
  $('#passwordMessage').textContent = forced
    ? 'Por seguridad, debe reemplazar la contraseña temporal antes de continuar.'
    : 'Escriba su contraseña actual y una nueva de al menos 8 caracteres.';
  $('#passwordCancel').classList.toggle('hidden', forced);
  $('#passwordDialog').classList.remove('hidden');
  $('#currentPassword').value = '';
  $('#newPassword').value = '';
  $('#repeatPassword').value = '';
  setTimeout(() => $('#currentPassword').focus(), 100);
}

function closePasswordDialog() {
  if (state.forcedPasswordChange) return;
  $('#passwordDialog').classList.add('hidden');
}

async function changeOwnPassword(event) {
  event.preventDefault();
  if ($('#newPassword').value !== $('#repeatPassword').value) {
    toast('Las contraseñas nuevas no coinciden.');
    return;
  }
  try {
    await api('/api/change-password', {
      method: 'POST',
      body: JSON.stringify({current_password: $('#currentPassword').value, new_password: $('#newPassword').value}),
    });
    const username = state.user?.username || '';
    $('#passwordDialog').classList.add('hidden');
    state.forcedPasswordChange = false;
    showLogin(false);
    $('#loginUsername').value = username;
    toast('Contraseña actualizada. Inicie sesión con la nueva contraseña.', 5200);
  } catch (error) { toast(error.message, 4800); }
}

async function loadAdminData() {
  if (!isAdmin()) return;
  try {
    const [departments, positions, users] = await Promise.all([
      api('/api/admin/departments'), api('/api/admin/positions'), api('/api/admin/users'),
    ]);
    state.adminData = {departments, positions, users};
    renderAdminDepartments();
    renderAdminPositions();
    renderAdminUsers();
  } catch (error) { toast(error.message); }
}

function renderAdminDepartments() {
  $('#departmentsAdminList').innerHTML = state.adminData.departments.map(dept => `
    <div class="admin-row">
      <div><strong>${escapeHtml(dept.name)}</strong><small>${escapeHtml(dept.code)} · ${dept.active_users} capturistas · ${dept.active_positions} puestos · ${dept.evaluations} evaluaciones</small></div>
      <button type="button" class="${dept.active ? 'secondary' : 'success'} compact" data-admin-action="department-active" data-id="${dept.id}" data-active="${dept.active ? '0' : '1'}">${dept.active ? 'Desactivar' : 'Activar'}</button>
    </div>`).join('') || '<p class="empty">Sin departamentos.</p>';
}

function renderAdminPositions() {
  const departmentId = Number($('#positionListDepartment').value || state.currentDepartmentId);
  const items = state.adminData.positions.filter(item => Number(item.department_id) === departmentId);
  $('#positionsAdminList').innerHTML = items.map(position => `
    <div class="admin-row">
      <div><strong>${escapeHtml(position.name)}</strong><small>${position.active ? 'Activo' : 'Desactivado'}</small></div>
      <button type="button" class="${position.active ? 'secondary' : 'success'} compact" data-admin-action="position-active" data-id="${position.id}" data-active="${position.active ? '0' : '1'}">${position.active ? 'Desactivar' : 'Activar'}</button>
    </div>`).join('') || '<p class="empty">Este departamento todavía no tiene puestos.</p>';
}

function renderAdminUsers() {
  $('#usersAdminList').innerHTML = state.adminData.users.map(user => `
    <div class="admin-row user-row">
      <div>
        <strong>${escapeHtml(user.display_name)}</strong>
        <small>@${escapeHtml(user.username)} · ${user.role === 'admin' ? 'Administrador' : escapeHtml(user.department_name || 'Sin departamento')} · ${user.active ? 'Activo' : 'Desactivado'}${user.must_change_password ? ' · Cambio de contraseña pendiente' : ''}</small>
      </div>
      <div class="record-actions">
        <button type="button" class="secondary compact" data-admin-action="reset-password" data-id="${user.id}" data-name="${escapeHtml(user.display_name)}">Contraseña</button>
        <button type="button" class="${user.active ? 'danger' : 'success'} compact" data-admin-action="user-active" data-id="${user.id}" data-active="${user.active ? '0' : '1'}">${user.active ? 'Desactivar' : 'Activar'}</button>
      </div>
    </div>`).join('');
}

async function createDepartment(event) {
  event.preventDefault();
  try {
    await api('/api/admin/departments', {
      method: 'POST',
      body: JSON.stringify({name: $('#departmentName').value, code: $('#departmentCode').value}),
    });
    event.target.reset();
    await refreshAdministrativeCatalogs();
    toast('Departamento agregado. Ahora puede crear sus puestos y capturistas.');
  } catch (error) { toast(error.message); }
}

async function createPosition(event) {
  event.preventDefault();
  try {
    await api('/api/admin/positions', {
      method: 'POST',
      body: JSON.stringify({department_id: Number($('#positionDepartment').value), name: $('#positionName').value}),
    });
    $('#positionName').value = '';
    $('#positionListDepartment').value = $('#positionDepartment').value;
    await refreshAdministrativeCatalogs();
    toast('Puesto agregado al departamento.');
  } catch (error) { toast(error.message); }
}

async function createCapturist(event) {
  event.preventDefault();
  try {
    await api('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        display_name: $('#userDisplayName').value,
        username: $('#userUsername').value,
        department_id: Number($('#userDepartment').value),
        password: $('#userPassword').value,
        role: 'capturist',
      }),
    });
    event.target.reset();
    await refreshAdministrativeCatalogs();
    toast('Capturista creado. Envíele el host, su usuario y la contraseña temporal.');
  } catch (error) { toast(error.message, 5200); }
}

async function handleAdminAction(event) {
  const button = event.target.closest('[data-admin-action]');
  if (!button) return;
  const action = button.dataset.adminAction;
  const id = Number(button.dataset.id);
  try {
    if (action === 'department-active') {
      await api(`/api/admin/departments/${id}/active`, {method: 'PUT', body: JSON.stringify({active: button.dataset.active === '1'})});
    } else if (action === 'position-active') {
      await api(`/api/admin/positions/${id}/active`, {method: 'PUT', body: JSON.stringify({active: button.dataset.active === '1'})});
    } else if (action === 'user-active') {
      const accepted = await confirmAction('Cambiar estado de cuenta', `La cuenta será ${button.dataset.active === '1' ? 'activada' : 'desactivada'}.`);
      if (!accepted) return;
      await api(`/api/admin/users/${id}/active`, {method: 'PUT', body: JSON.stringify({active: button.dataset.active === '1'})});
    } else if (action === 'reset-password') {
      $('#resetPasswordUserId').value = String(id);
      $('#resetPasswordUser').textContent = `Cuenta: ${button.dataset.name}`;
      $('#resetPasswordValue').value = '';
      $('#resetPasswordDialog').classList.remove('hidden');
      setTimeout(() => $('#resetPasswordValue').focus(), 80);
      return;
    }
    await refreshAdministrativeCatalogs();
    toast('Cambio administrativo guardado.');
  } catch (error) { toast(error.message, 5200); }
}

async function resetUserPassword(event) {
  event.preventDefault();
  try {
    await api(`/api/admin/users/${Number($('#resetPasswordUserId').value)}/password`, {
      method: 'PUT', body: JSON.stringify({password: $('#resetPasswordValue').value}),
    });
    $('#resetPasswordDialog').classList.add('hidden');
    await loadAdminData();
    toast('Contraseña temporal restablecida. El usuario deberá cambiarla al entrar.');
  } catch (error) { toast(error.message); }
}

async function refreshAdministrativeCatalogs() {
  const previous = state.currentDepartmentId;
  let bootstrap = await api(`/api/bootstrap?department_id=${previous || ''}`);
  const previousStillActive = bootstrap.departments.some(item => Number(item.id) === Number(bootstrap.catalog.department?.id));
  if (!previousStillActive && bootstrap.departments.length) bootstrap = await api('/api/bootstrap');
  state.bootstrap = bootstrap;
  state.user = state.bootstrap.user;
  state.catalog = state.bootstrap.catalog;
  state.currentDepartmentId = state.catalog.department?.id || state.bootstrap.departments[0]?.id || null;
  populateDepartmentSelectors();
  populateCatalogs();
  updateSessionHeader();
  prepareBlankCapture();
  await loadAdminData();
}

function isTextEntry(element) {
  if (element instanceof HTMLTextAreaElement) return true;
  if (!(element instanceof HTMLInputElement)) return false;
  return !['button', 'checkbox', 'radio', 'date', 'file', 'submit', 'hidden'].includes(element.type);
}

function setupKeyboardAwareActions() {
  const viewport = window.visualViewport;
  const visibleHeight = () => viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
  state.baseViewportHeight = Math.max(window.innerHeight, visibleHeight());
  const update = () => {
    const activeTextEntry = isTextEntry(document.activeElement);
    const currentVisibleHeight = visibleHeight();
    if (!activeTextEntry) state.baseViewportHeight = Math.max(window.innerHeight, currentVisibleHeight);
    const keyboardOffset = activeTextEntry ? Math.max(0, state.baseViewportHeight - currentVisibleHeight) : 0;
    const keyboardOpen = keyboardOffset > 80;
    document.documentElement.style.setProperty('--keyboard-offset', `${keyboardOpen ? keyboardOffset : 0}px`);
    document.body.classList.toggle('keyboard-open', keyboardOpen);
  };
  document.addEventListener('focusin', event => {
    if (!isTextEntry(event.target)) return;
    setTimeout(() => {
      update();
      event.target.scrollIntoView({block: 'center', behavior: 'smooth'});
    }, 180);
  });
  document.addEventListener('focusout', () => setTimeout(update, 180));
  window.addEventListener('resize', update);
  window.addEventListener('orientationchange', () => setTimeout(() => {
    state.baseViewportHeight = Math.max(window.innerHeight, visibleHeight());
    update();
  }, 450));
  if (viewport) {
    viewport.addEventListener('resize', update);
    viewport.addEventListener('scroll', update);
  }
  update();
}

function startVoice(targetId, append) {
  const input = document.getElementById(targetId);
  if (!input) return;
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    input.focus();
    toast('Este navegador no ofrece voz automática. Use el micrófono del teclado Android.');
    return;
  }
  if (state.recognition) {
    try { state.recognition.stop(); } catch (_) {}
  }
  const recognition = new Recognition();
  state.recognition = recognition;
  state.voiceTarget = targetId;
  recognition.lang = 'es-MX';
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.maxAlternatives = 3;
  $('#voiceStatus').textContent = '🔴 Escuchando…';
  $('#voiceStatus').classList.add('listening');
  input.focus();
  recognition.onresult = event => {
    const transcript = [...event.results].map(result => result[0].transcript).join(' ').trim();
    if (!transcript) return;
    input.value = append && input.value.trim() ? `${input.value.trim()} ${transcript}` : transcript;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    input.dispatchEvent(new Event('change', {bubbles: true}));
  };
  recognition.onerror = event => {
    const messages = {'not-allowed':'Autorice el micrófono en Chrome.','no-speech':'No se detectó voz; puede intentarlo de nuevo.','network':'La voz del navegador requiere conexión disponible.'};
    toast(messages[event.error] || `No fue posible reconocer la voz (${event.error}).`);
  };
  recognition.onend = () => {
    $('#voiceStatus').textContent = '🎙 Voz lista';
    $('#voiceStatus').classList.remove('listening');
    state.recognition = null;
    state.voiceTarget = null;
  };
  try { recognition.start(); } catch (_) { toast('Toque nuevamente el micrófono para iniciar el dictado.'); }
}

function debounce(fn, wait) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

async function init() {
  bindEvents();
  await restoreSession();
}

document.addEventListener('DOMContentLoaded', init);
