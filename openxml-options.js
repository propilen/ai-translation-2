const generalFields = [
  ['bPreferenceTranslateDocProperties', 'Переводить свойства документа'],
  ['bPreferenceTranslateComments', 'Переводить комментарии'],
  ['bPreferenceAggressiveCleanup', 'Агрессивно очищать теги'],
  ['bPreferenceAddTabAsCharacter', 'Обрабатывать табуляцию как символ'],
  ['bPreferenceAddLineSeparatorAsCharacter', 'Обрабатывать разрыв строки как символ'],
  ['bExtractExternalHyperlinks', 'Извлекать внешние гиперссылки'],
];
const pageFields = {
  word: [
    ['bPreferenceTranslateWordHeadersFooters', 'Переводить колонтитулы'],
    ['translateWordNumberingLevelText', 'Переводить текст уровней нумерации'],
    ['bPreferenceTranslateWordHidden', 'Переводить скрытый текст'],
    ['bPreferenceTranslateWordExcludeGraphicMetaData', 'Исключать графические метаданные'],
    ['bPreferenceAutomaticallyAcceptRevisions', 'Автоматически принимать исправления'],
    ['bPreferenceIgnoreSoftHyphenTag', 'Игнорировать мягкие переносы'],
    ['bPreferenceReplaceNoBreakHyphenTag', 'Заменять неразрывный дефис обычным'],
    ['allowWordStyleOptimisation', 'Разрешить оптимизацию стилей'],
  ],
  excel: [
    ['bPreferenceTranslateExcelHidden', 'Переводить скрытые строки и столбцы'],
    ['bPreferenceTranslateExcelSheetNames', 'Переводить имена листов'],
    ['translateExcelCellsCopied', 'Переводить повторяющиеся ячейки отдельно'],
    ['bPreferenceTranslateExcelDiagramData', 'Переводить данные диаграмм (SmartArt)'],
    ['bPreferenceTranslateExcelDrawings', 'Переводить рисунки (текстовые поля)'],
    ['preserveExcelStylesInTargetColumns', 'Сохранять стили целевых столбцов'],
  ],
  powerpoint: [
    ['translatePowerpointDocProperties', 'Переводить свойства документа'],
    ['reorderPowerpointDocProperties', 'Переупорядочивать свойства документа'],
    ['translatePowerpointDiagramData', 'Переводить данные диаграмм'],
    ['reorderPowerpointDiagramData', 'Переупорядочивать данные диаграмм'],
    ['translatePowerpointCharts', 'Переводить диаграммы'],
    ['reorderPowerpointCharts', 'Переупорядочивать диаграммы'],
    ['bPreferenceTranslatePowerpointNotes', 'Переводить заметки'],
    ['bPreferenceReorderPowerpointNotes', 'Переупорядочивать заметки'],
    ['translatePowerpointComments', 'Переводить комментарии'],
    ['reorderPowerpointComments', 'Переупорядочивать комментарии'],
    ['bPreferenceTranslatePowerpointMasters', 'Переводить мастер-слайды'],
    ['bPreferenceIgnorePlaceholdersInPowerpointMasters', 'Игнорировать текст заполнителей в мастерах'],
    ['bPreferencePowerpointIncludedSlideNumbersOnly', 'Переводить только выбранные номера слайдов'],
    ['bReorderPowerpointNotesAndComments', 'Переупорядочивать связи заметок и комментариев'],
  ],
};
const page = document.body.dataset.page;
const form = document.getElementById('options-form');
const status = document.getElementById('status');
let current = null;
const checkbox = ([key, label]) => `<label><input type="checkbox" name="${key}"> <span>${label}</span></label>`;
const listField = (key, label, hint = 'По одному значению в строке.') => `<label>${label}<textarea name="${key}" data-list>${''}</textarea><span class="hint">${hint}</span></label>`;

function renderGeneral() {
  document.getElementById('general-options').className = 'settings-section';
  document.getElementById('general-options').innerHTML = `<h2>Общие параметры</h2><p>Эти параметры применяются к Word, Excel и PowerPoint.</p><div class="checks">${generalFields.map(checkbox).join('')}</div>`;
}

function renderWord() {
  document.getElementById('format-options').className = 'settings-section';
  document.getElementById('format-options').innerHTML = `<h2>Word Options</h2><p>Параметры извлечения DOCX.</p><div class="checks">${pageFields.word.map(checkbox).join('')}</div><div class="grid format-extra"><div class="wide"><label>Переводимые поля Word${listField('translate_fields', '', 'Например: HYPERLINK, FORMTEXT, TOC.').replace('<label>', '').replace('</label>', '')}</label></div>${listField('word_styles', 'Исключаемые / включаемые стили')}<div><label>Режим стилей</label><div class="choice"><label><input type="radio" name="bInExcludeMode" value="true"> Исключать</label><label><input type="radio" name="bInExcludeMode" value="false"> Включать только перечисленные</label></div></div>${listField('word_highlight_colours', 'Цвета выделения')}<div><label>Режим цветов выделения</label><div class="choice"><label><input type="radio" name="bInExcludeHighlightMode" value="true"> Исключать</label><label><input type="radio" name="bInExcludeHighlightMode" value="false"> Включать только перечисленные</label></div></div>${listField('word_excluded_colours', 'Исключаемые цвета шрифта')}<label>Минимальный порог игнорирования цветов<input type="text" name="wordFontColoursMinimumIgnoranceThreshold" placeholder="например, 000000"></label><label>Максимальный порог игнорирования цветов<input type="text" name="wordFontColoursMaximumIgnoranceThreshold" placeholder="например, FFFFFF"></label></div>`;
}

function worksheetRow(row = {}) {
  const fields = [['namePattern','Шаблон имени'],['sourceColumns','Исходные'],['targetColumns','Целевые'],['targetColumnsMaxCharacters','Ограничения'],['excludedRows','Искл. строки'],['excludedColumns','Искл. столбцы'],['metadataRows','Метаданные: строки'],['metadataColumns','Метаданные: столбцы']];
  return `<tr>${fields.map(([key, title]) => `<td><input aria-label="${title}" name="${key}" value="${escapeHtml(row[key] || '')}"></td>`).join('')}<td><button class="remove-row" type="button">Удалить</button></td></tr>`;
}

function renderExcel() {
  document.getElementById('format-options').className = 'settings-section';
  document.getElementById('format-options').innerHTML = `<h2>Excel Options</h2><p>Параметры извлечения XLSX. Для колонок используйте обозначения Excel: <code>A,B</code>; для строк — <code>1,2</code>.</p><div class="checks">${pageFields.excel.map(checkbox).join('')}</div><div class="grid format-extra">${listField('excel_excluded_colours', 'Исключаемые цвета', 'Один цвет на строку: имя из палитры Excel или RGB без #, например 69b3e7.')}<label>Имя субфильтра для содержимого ячеек<input type="text" name="subfilter"></label><div class="wide"><label>Конфигурации листов</label><div class="table-wrap"><table class="worksheet-table"><thead><tr><th>Шаблон имени</th><th>Исходные столбцы</th><th>Целевые столбцы</th><th>Ограничения</th><th>Искл. строки</th><th>Искл. столбцы</th><th>Метаданные: строки</th><th>Метаданные: столбцы</th><th></th></tr></thead><tbody id="worksheet-rows"></tbody></table></div><p><button id="add-worksheet" class="add-row" type="button">Добавить лист</button></p><span class="hint">«Ограничения» соответствует <code>targetColumnsMaxCharacters</code>; можно указать столбец ограничения с дефолтом, например <code>C:20</code>.</span></div></div>`;
  document.getElementById('add-worksheet').addEventListener('click', () => document.getElementById('worksheet-rows').insertAdjacentHTML('beforeend', worksheetRow()));
}

function renderPowerPoint() {
  document.getElementById('format-options').className = 'settings-section';
  document.getElementById('format-options').innerHTML = `<h2>PowerPoint Options</h2><p>Параметры извлечения PPTX.</p><div class="checks">${pageFields.powerpoint.map(checkbox).join('')}</div><div class="grid format-extra">${listField('powerpoint_slide_numbers', 'Номера включаемых слайдов', 'По одному номеру слайда в строке. Используется, когда включён параметр «только выбранные номера слайдов».')}</div>`;
}

function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }

function fill(data) {
  current = data;
  for (const input of form.querySelectorAll('input[type=checkbox]')) input.checked = Boolean(data[input.name]);
  for (const input of form.querySelectorAll('input[type=text]')) input.value = data[input.name] || '';
  for (const area of form.querySelectorAll('textarea[data-list]')) area.value = (data[area.name] || []).join('\n');
  for (const name of ['bInExcludeMode', 'bInExcludeHighlightMode']) {
    const radio = form.querySelector(`input[name="${name}"][value="${Boolean(data[name])}"]`); if (radio) radio.checked = true;
  }
  if (page === 'excel') document.getElementById('worksheet-rows').innerHTML = (data.worksheet_configurations || []).map(worksheetRow).join('');
}

function payload() {
  const values = {};
  for (const input of form.querySelectorAll('input[type=checkbox]')) values[input.name] = input.checked;
  for (const input of form.querySelectorAll('input[type=text]')) values[input.name] = input.value.trim();
  for (const area of form.querySelectorAll('textarea[data-list]')) values[area.name] = area.value.split(/\r?\n/).map(value => value.trim()).filter(Boolean);
  for (const name of ['bInExcludeMode', 'bInExcludeHighlightMode']) { const selected = form.querySelector(`input[name="${name}"]:checked`); if (selected) values[name] = selected.value === 'true'; }
  if (page === 'excel') values.worksheet_configurations = [...document.querySelectorAll('#worksheet-rows tr')].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.name, input.value.trim()]))).filter(row => Object.values(row).some(Boolean));
  return { values };
}

async function load() { const response = await fetch('/api/openxml-options'); if (!response.ok) throw new Error('Не удалось загрузить параметры OpenXML.'); fill(await response.json()); }
form.addEventListener('click', event => { if (event.target.classList.contains('remove-row')) event.target.closest('tr').remove(); });
form.addEventListener('submit', async event => { event.preventDefault(); status.textContent = 'Сохраняем…'; status.className = ''; try { const response = await fetch('/api/openxml-options', {method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload())}); const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить настройки.'); fill(data); await afterTemplateSaved(data); status.textContent = `Сохранено: ${data.configuration_path}`; status.className = 'ok'; } catch (error) { status.textContent = error.message; status.className = 'error'; } });
renderGeneral(); if (page === 'word') renderWord(); if (page === 'excel') renderExcel(); if (page === 'powerpoint') renderPowerPoint(); load().catch(error => { status.textContent = error.message; status.className = 'error'; });

function renderWord() {
  document.getElementById('format-options').innerHTML = `<h2>Параметры обработки MS Word</h2><p>Параметры извлечения DOCX.</p><div class="checks">${pageFields.word.map(checkbox).join('')}</div><div class="grid format-extra"><div class="wide"><label>Переводимые поля Word</label><div id="detected-fields" class="selectable"></div><span class="hint">Зелёные поля переводятся; нажмите, чтобы исключить поле.</span></div><div class="wide"><label>Исключаемые / включаемые стили</label><div id="detected-styles" class="selectable"></div><span class="hint">Зелёные стили переводятся; красные исключаются.</span></div><div class="wide"><label>Цвета выделения</label><div id="detected-highlights" class="selectable"></div><span class="hint">Зелёные цвета переводятся; красные исключаются.</span></div></div>`;
}

function setChips(id, values) {
  const container = document.getElementById(id);
  container.innerHTML = values.length ? values.map(value => `<button class="option-chip" type="button" data-value="${escapeHtml(value)}">${escapeHtml(value)}</button>`).join('') : '<span class="hint">Не обнаружено.</span>';
  container.querySelectorAll('.option-chip').forEach(chip => chip.addEventListener('click', () => chip.classList.toggle('is-off')));
}

function chipValues(id, selected) {
  return [...document.querySelectorAll(`#${id} .option-chip`)].filter(chip => chip.classList.contains('is-off') !== selected).map(chip => chip.dataset.value);
}

async function analyseDocument(file) {
  const analysisStatus = document.getElementById('analysis-status');
  analysisStatus.textContent = ' Анализируем…';
  const body = new FormData(); body.append('document', file);
  try {
    const response = await fetch('/api/openxml-options/analyze', { method: 'POST', body });
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || 'Не удалось прочитать DOCX.');
    setChips('detected-fields', data.fields);
    setChips('detected-styles', data.styles);
    setChips('detected-highlights', data.highlights);
    analysisStatus.textContent = ` ${file.name}: параметры обновлены.`;
  } catch (error) { analysisStatus.textContent = ` ${error.message}`; }
}

function fill(data) {
  current = data;
  for (const input of form.querySelectorAll('input[type=checkbox]')) input.checked = Boolean(data[input.name]);
  for (const input of form.querySelectorAll('input[type=text]')) input.value = data[input.name] || '';
  if (page === 'excel') document.getElementById('worksheet-rows').innerHTML = (data.worksheet_configurations || []).map(worksheetRow).join('');
}

function payload() {
  const values = {};
  for (const input of form.querySelectorAll('input[type=checkbox]')) values[input.name] = input.checked;
  for (const input of form.querySelectorAll('input[type=text]')) values[input.name] = input.value.trim();
  if (page === 'word') {
    values.translate_fields = chipValues('detected-fields', true);
    values.word_styles = chipValues('detected-styles', false);
    values.word_highlight_colours = chipValues('detected-highlights', false);
    values.bInExcludeMode = true;
    values.bInExcludeHighlightMode = true;
  }
  if (page === 'excel') values.worksheet_configurations = [...document.querySelectorAll('#worksheet-rows tr')].map(row => Object.fromEntries([...row.querySelectorAll('input')].map(input => [input.name, input.value.trim()]))).filter(row => Object.values(row).some(Boolean));
  return { values, template_name: page === 'word' ? (selectedTemplateId || 'okf_openxml@copy-of-default.fprm').replace(/^okf_openxml@/, '').replace(/\.fprm$/, '') : 'copy-of-default' };
}

if (page === 'word') document.getElementById('analysis-document').addEventListener('change', event => { if (event.target.files[0]) analyseDocument(event.target.files[0]); });

let selectedTemplateId = '';

function templateIdFromData(data) {
  return (data.configuration_path || '').replace(/^.*[\\/]/, '');
}

function updateDeleteButton() {
  const button = document.getElementById('delete-template');
  if (!button) return;
  button.disabled = !selectedTemplateId || selectedTemplateId === 'okf_openxml@copy-of-default.fprm';
}

async function readTemplates() {
  const response = await fetch('/api/word-templates');
  if (!response.ok) throw new Error('Не удалось получить список шаблонов.');
  return (await response.json()).templates || [];
}

function renderTemplateOptions(templates, selectedId) {
  const saved = templates.filter(template => template.custom);
  const selector = document.getElementById('template-selector');
  const baseSelector = document.getElementById('base-template-selector');
  if (!saved.length) {
    selector.innerHTML = '<option value="">Нет сохранённых шаблонов</option>';
    selector.disabled = true;
  } else {
    selector.disabled = false;
    selector.innerHTML = saved.map(template => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.label)}</option>`).join('');
    selector.value = saved.some(template => template.id === selectedId) ? selectedId : saved[0].id;
  }
  baseSelector.innerHTML = templates.map(template => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.label)}</option>`).join('');
  baseSelector.value = selectedTemplateId || (saved[0] && saved[0].id) || '';
}

async function loadSelectedTemplate(templateId) {
  const response = await fetch(`/api/openxml-options?template_id=${encodeURIComponent(templateId)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'Не удалось загрузить шаблон.');
  selectedTemplateId = templateId;
  fill(data);
  updateDeleteButton();
}

async function refreshTemplateControls(preferredId = '') {
  const templates = await readTemplates();
  renderTemplateOptions(templates, preferredId || selectedTemplateId);
  const selector = document.getElementById('template-selector');
  const nextId = selector.disabled ? '' : selector.value;
  if (nextId) await loadSelectedTemplate(nextId);
  else updateDeleteButton();
}

async function afterTemplateSaved(data) {
  if (page !== 'word') return;
  const id = templateIdFromData(data);
  selectedTemplateId = id;
  await refreshTemplateControls(id);
}

if (page === 'word') {
  const templateSelector = document.getElementById('template-selector');
  const dialog = document.getElementById('new-template-dialog');
  const newTemplateForm = document.getElementById('new-template-form');
  const newTemplateStatus = document.getElementById('new-template-status');

  templateSelector.addEventListener('change', async () => {
    try { await loadSelectedTemplate(templateSelector.value); }
    catch (error) { status.textContent = error.message; status.className = 'error'; }
  });
  document.getElementById('new-template').addEventListener('click', () => {
    newTemplateStatus.textContent = '';
    document.getElementById('new-template-name').value = '';
    document.getElementById('base-template-selector').value = selectedTemplateId || '';
    dialog.showModal();
    document.getElementById('new-template-name').focus();
  });
  dialog.querySelector('.dialog-cancel').addEventListener('click', () => dialog.close());
  newTemplateForm.addEventListener('submit', async event => {
    event.preventDefault();
    newTemplateStatus.textContent = 'Создаём…';
    try {
      const response = await fetch('/api/openxml-options/templates', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({template_name: document.getElementById('new-template-name').value.trim(), base_template_id: document.getElementById('base-template-selector').value})});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось создать шаблон.');
      const id = templateIdFromData(data);
      selectedTemplateId = id;
      fill(data);
      await refreshTemplateControls(id);
      dialog.close();
      status.textContent = 'Новый шаблон создан.';
      status.className = 'ok';
    } catch (error) { newTemplateStatus.textContent = error.message; }
  });
  document.getElementById('delete-template').addEventListener('click', async () => {
    if (!selectedTemplateId || !confirm('Удалить текущий шаблон? Это действие нельзя отменить.')) return;
    try {
      const response = await fetch(`/api/openxml-options/templates/${encodeURIComponent(selectedTemplateId)}`, {method: 'DELETE'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Не удалось удалить шаблон.');
      selectedTemplateId = '';
      await refreshTemplateControls();
      status.textContent = 'Шаблон удалён.';
      status.className = 'ok';
    } catch (error) { status.textContent = error.message; status.className = 'error'; }
  });
  refreshTemplateControls().catch(error => { status.textContent = error.message; status.className = 'error'; });
}
const navigationScript = document.createElement('script'); navigationScript.src = '/app-navigation.js'; document.body.append(navigationScript);
if (page === 'word') { const layoutStyles = document.createElement('link'); layoutStyles.rel = 'stylesheet'; layoutStyles.href = '/settings-layout.css'; document.head.append(layoutStyles); const layoutScript = document.createElement('script'); layoutScript.src = '/settings-layout.js'; document.body.append(layoutScript); }
