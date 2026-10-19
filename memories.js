const $ = id => document.getElementById(id);
let step = 1, memories = [], searching = false, searchVersion = 0;
const memoryTabs = ['search', 'import'];
function activateMemoryTab(name, updateHash = false) {
  const active = memoryTabs.includes(name) ? name : 'search';
  memoryTabs.forEach(tabName => {
    const selected = tabName === active;
    $('tab-' + tabName).setAttribute('aria-selected', String(selected));
    $('tab-' + tabName).tabIndex = selected ? 0 : -1;
    $('panel-' + tabName).hidden = !selected;
  });
  if (updateHash && location.hash !== '#' + active) history.replaceState(null, '', '#' + active);
}
memoryTabs.forEach((name, index) => {
  $('tab-' + name).addEventListener('click', () => activateMemoryTab(name, true));
  $('tab-' + name).addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? memoryTabs.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + memoryTabs.length) % memoryTabs.length;
    activateMemoryTab(memoryTabs[next], true);
    $('tab-' + memoryTabs[next]).focus();
  });
});
window.addEventListener('hashchange', () => activateMemoryTab(location.hash.slice(1)));
activateMemoryTab(location.hash.slice(1));
function message(id, text, error = false) { $(id).textContent = text; $(id).classList.toggle('error', error); }
async function api(url, options) {
  const response = await fetch(url, options);
  if (response.status === 401) { location.assign('/login'); throw new Error('Сессия завершена. Войдите в сервис.'); }
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === 'string' ? body.detail : 'Не удалось выполнить запрос.'); }
  return response.json();
}
function appendHighlightedText(element, text, query, mode, respectCase, useRegex) {
  if (!query) { element.textContent = text; return; }
  const flags = respectCase ? 'gu' : 'giu';
  const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  try {
    let pattern;
    if (useRegex) pattern = new RegExp(query, flags);
    else if (mode === 'phrase') pattern = new RegExp('(?<![\\p{L}\\p{N}_])' + escape(query.trim()) + '(?![\\p{L}\\p{N}_])', flags);
    else {
      const words = [...new Set(query.match(/[\p{L}\p{N}_]+/gu) || [])];
      if (!words.length) { element.textContent = text; return; }
      pattern = new RegExp('(?<![\\p{L}\\p{N}_])(?:' + words.map(escape).join('|') + ')(?![\\p{L}\\p{N}_])', flags);
    }
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      element.append(document.createTextNode(text.slice(cursor, match.index)));
      const mark = document.createElement('mark'); mark.className = 'search-highlight'; mark.textContent = match[0]; element.append(mark);
      cursor = match.index + match[0].length;
    }
    element.append(document.createTextNode(text.slice(cursor)));
  } catch (_) { element.textContent = text; }
}
function languageLabel(code) { const names = {ru:'Русский', en:'Английский', de:'Немецкий'}; return `${names[String(code).split('-')[0].toLowerCase()] || code} (${code})`; }
function modeLabel(item, mode) {
  if (item.matched_modes?.includes('regex')) return 'Рег. выражение';
  if (mode === 'all') return (item.exact ? '100% — Точное' : '') + (item.exact ? ' · ' : '') + item.matched_modes.map(value => ({phrase:'Фраза', words:'Все слова', fuzzy:`Fuzzy ${item.score}%`})[value]).join(' · ');
  if (mode === 'fuzzy') return `${item.score}% — ${item.exact ? 'Точное' : 'Fuzzy'}`;
  return mode === 'words' ? 'Все слова' : 'Фраза';
}
function copyButton(value, label) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'copy-cell-text'; button.title = `Копировать ${label}`; button.setAttribute('aria-label', `Копировать ${label}`);
  button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="10" height="11" rx="2"/><path d="M15 9V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>';
  button.addEventListener('click', async event => {
    event.stopPropagation();
    try { await navigator.clipboard.writeText(value); }
    catch (_) { const area = document.createElement('textarea'); area.value = value; area.style.cssText = 'position:fixed;opacity:0'; document.body.append(area); area.select(); document.execCommand('copy'); area.remove(); }
    button.classList.add('is-copied'); button.title = 'Скопировано';
    setTimeout(() => { button.classList.remove('is-copied'); button.title = `Копировать ${label}`; }, 1300);
  });
  return button;
}
function showStep(value) {
  step = value;
  for (let i = 1; i <= 3; i++) { $('step-' + i).hidden = i !== step; $('step-' + i).disabled = i !== step; const item = document.querySelectorAll('.steps li')[i - 1]; if (i === step) item.setAttribute('aria-current', 'step'); else item.removeAttribute('aria-current'); }
  $('step-count').textContent = `Шаг ${step} из 3`; $('back').hidden = step === 1; $('next').hidden = step === 3; $('import').hidden = step !== 3;
  if (step === 3) {
    const destination = memories.find(memory => memory.id === $('import-destination').value);
    const title = destination ? `Добавление в: ${destination.name}` : `Новая память: ${$('memory-name').value.trim() || $('tmx').files[0].name.replace(/\.tmx$/i, '')}`;
    const note = destination ? 'Будут добавлены только новые пары сегментов.' : $('description').value;
    $('review').textContent = [`Файл: ${$('tmx').files[0].name}`, title, `Языки: ${$('source').value} → ${$('target').value}`, note].filter(Boolean).join('\n');
  }
}
$('tmx').addEventListener('change', () => { $('filename').textContent = $('tmx').files[0]?.name || ''; });
$('next').addEventListener('click', () => { message('import-status', ''); if (!$('import-form').reportValidity()) return; if (step === 1 && !/\.tmx$/i.test($('tmx').files[0].name)) return message('import-status', 'Выберите файл TMX.', true); if (step === 2 && (!$('source').value.trim() || !$('target').value.trim() || $('source').value.trim().toLowerCase() === $('target').value.trim().toLowerCase())) return message('import-status', 'Укажите разные коды языков.', true); showStep(step + 1); });
$('back').addEventListener('click', () => showStep(step - 1));
$('import-form').addEventListener('submit', async event => {
  event.preventDefault(); if (step !== 3) { $('next').click(); return; }
  const data = new FormData(); data.append('document', $('tmx').files[0]); for (const [key, id] of [['name','memory-name'],['description','description'],['source_language','source'],['target_language','target'],['existing_memory_id','import-destination']]) data.append(key, $(id).value.trim());
  $('import').disabled = $('back').disabled = true; message('import-status', 'Файл загружается и импортируется. Дождитесь завершения…');
  try { const memory = await api('/api/memories', {method:'POST', body:data}); const merged = Boolean($('import-destination').value); $('import-form').reset(); updateImportDestination(); showStep(1); $('filename').textContent = ''; message('import-status', merged ? `Память «${memory.name}» обновлена. Добавлено: ${memory.added}. Всего сегментов: ${memory.count}. Пропущено: ${memory.skipped}. Дубликатов: ${memory.duplicates}.` : `Память «${memory.name}» готова. Импортировано: ${memory.added}. Пропущено: ${memory.skipped}. Дубликатов: ${memory.duplicates}.`); await loadMemories(memory.id); }
  catch (error) { message('import-status', error.message, true); } finally { $('import').disabled = $('back').disabled = false; }
});
function selectMemory() { searchVersion++; const memory = memories.find(item => item.id === $('memory').value); $('results').replaceChildren(); message('search-status',''); $('search-button').disabled = !memory || searching; $('download').hidden = $('download-tmx').hidden = !memory; $('memory-details').textContent = memory ? `${memory.source_language} → ${memory.target_language} · ${memory.count} сегментов${memory.description ? ' · ' + memory.description : ''}` : 'Загрузите первый TMX через мастер выше.'; if (memory) { $('download').href = `/api/memories/${memory.id}/download`; $('download-tmx').href = `/api/memories/${memory.id}/download-tmx`; } }
function updateImportDestination() { const memory = memories.find(item => item.id === $('import-destination').value); ['memory-name','description','source','target'].forEach(id => { $(id).disabled = Boolean(memory); }); if (memory) { $('memory-name').value = memory.name; $('description').value = memory.description || ''; $('source').value = memory.source_language; $('target').value = memory.target_language; } }
async function loadMemories(selected) { try { memories = await api('/api/memories'); const currentDestination = $('import-destination').value; $('memory').replaceChildren(new Option(memories.length ? 'Выберите память' : 'Пока нет загруженных памятей','')); $('import-destination').replaceChildren(new Option('Новую память переводов', '')); memories.forEach(item => { $('memory').add(new Option(`${item.name} (${item.source_language} → ${item.target_language})`, item.id)); $('import-destination').add(new Option(`Добавить в «${item.name}» (${item.source_language} → ${item.target_language})`, item.id)); }); $('memory').value = selected || memories[0]?.id || ''; $('import-destination').value = memories.some(item => item.id === currentDestination) ? currentDestination : ''; updateImportDestination(); selectMemory(); } catch (error) { message('search-status',error.message,true); } }
$('memory').addEventListener('change', selectMemory); $('import-destination').addEventListener('change', updateImportDestination);
function validateRegexField(inputId, statusId) { const value = $(inputId).value, status = $(statusId); if (!$('use-regex').checked || !value) { status.textContent = ''; status.className = 'hint'; return true; } try { new RegExp(value, 'u'); status.textContent = 'Синтаксис регулярного выражения корректен.'; status.className = 'hint regex-valid'; return true; } catch (error) { status.textContent = `Ошибка синтаксиса: ${error.message}`; status.className = 'hint regex-invalid'; return false; } }
function validateRegex() { return validateRegexField('query','source-regex-status') && validateRegexField('target-query','target-regex-status'); }
function updateSearchMode() { searchVersion++; const mode = $('search-mode').value; $('threshold-field').hidden = !['fuzzy','all'].includes(mode) || $('use-regex').checked; $('threshold').disabled = $('threshold-field').hidden; $('search-hint').textContent = $('use-regex').checked ? 'Введите регулярное выражение в поле оригинала, перевода или в обоих полях. Если заполнены оба поля, оба выражения должны совпасть.' : ({all:'Объединяет фразу, все слова и Fuzzy без повторов.',fuzzy:'100% — совпадение после нормализации регистра и пробелов. Меньший порог включает fuzzy-совпадения.',words:'Все введённые слова должны встретиться в тексте целиком, в любом порядке.',phrase:'Фраза должна встретиться внутри текста целиком и в том же порядке.'}[mode]); $('query').placeholder = $('use-regex').checked ? 'Регулярное выражение для оригинала' : 'Введите текст оригинала'; $('target-query').placeholder = $('use-regex').checked ? 'Регулярное выражение для перевода' : 'Введите текст перевода'; $('results').replaceChildren(); message('search-status',''); }
$('search-mode').addEventListener('change', updateSearchMode); $('use-regex').addEventListener('change', () => { validateRegex(); updateSearchMode(); });
for (const field of [$('query'),$('target-query')]) { field.addEventListener('input',validateRegex); field.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('search-form').requestSubmit(); } }); }
$('search-form').addEventListener('submit', async event => {
  event.preventDefault(); const query = $('query').value, targetQuery = $('target-query').value, useRegex = $('use-regex').checked, respectCase = $('respect-case').checked;
  if (!query.trim() && !targetQuery.trim()) return message('search-status','Введите текст оригинала или перевода.',true); if (!validateRegex()) return message('search-status','Исправьте регулярное выражение.',true);
  const memoryId = $('memory').value, mode = $('search-mode').value, version = ++searchVersion; searching = true; $('search-button').disabled = true; $('results').replaceChildren(); message('search-status','Ищем совпадения…');
  try {
    const params = new URLSearchParams({source_q:query,target_q:targetQuery,use_regex:useRegex,respect_case:respectCase,mode}); if (mode === 'fuzzy' || mode === 'all') params.set('threshold',$('threshold').value);
    const data = await api(`/api/memories/${memoryId}/search?${params}`); if (version !== searchVersion) return; const memory = memories.find(item => item.id === memoryId);
    message('search-status', data.results.length ? `Показано совпадений: ${data.results.length}. ${useRegex ? 'Поиск по регулярному выражению' : mode === 'all' ? 'Сначала точные совпадения, фразы, все слова, затем Fuzzy' : mode === 'fuzzy' ? 'По убыванию сходства' : 'В порядке сегментов памяти'}, максимум ${data.limit}.` : 'Совпадений нет. Проверьте текст или параметры поиска.');
    if (data.results.length) {
      const table = document.createElement('table'); table.className = 'memory-results';
      const head = document.createElement('thead'), header = document.createElement('tr');
      ['№ сегмента', languageLabel(memory.source_language), '% совпадения\nи режим', languageLabel(memory.target_language)].forEach(label => {
        const cell = document.createElement('th'); cell.textContent = label; header.append(cell);
      });
      head.append(header); table.append(head); const body = document.createElement('tbody');
      data.results.forEach(item => {
        const row = document.createElement('tr'), number = document.createElement('td'), source = document.createElement('td'), result = document.createElement('td'), target = document.createElement('td');
        row.tabIndex = 0; row.setAttribute('aria-label', `Сегмент ${item.id}`);
        const select = () => { table.querySelectorAll('tbody tr.is-selected').forEach(current => current.classList.remove('is-selected')); row.classList.add('is-selected'); };
        row.addEventListener('click', select); row.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } });
        number.className = 'segment-number'; source.className = target.className = 'cell-text'; result.className = 'match-mode';
        number.textContent = item.id; result.textContent = modeLabel(item, mode);
        const textMode = mode === 'all' && item.matched_modes.includes('phrase') ? 'phrase' : mode;
        appendHighlightedText(source, item.source, query, textMode, respectCase, useRegex); source.append(copyButton(item.source, 'оригинал'));
        appendHighlightedText(target, item.target, targetQuery, textMode, respectCase, useRegex); target.append(copyButton(item.target, 'перевод'));
        row.append(number, source, result, target); body.append(row);
      });
      table.append(body); $('results').append(table);
    }
  } catch (error) { if (version === searchVersion) message('search-status',error.message,true); } finally { searching=false; $('search-button').disabled=!$('memory').value; }
});
validateRegex(); updateSearchMode(); showStep(1); loadMemories();
