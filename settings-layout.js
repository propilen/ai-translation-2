(() => {
  const form = document.querySelector('.settings-form');
  if (!form || form.closest('.settings-workspace')) return;
  const isWord = document.body.dataset.page === 'word';
  if (isWord) {
    const toolbar = document.createElement('div');
    toolbar.className = 'template-toolbar'; toolbar.id = 'template-tools';
    const selector = document.querySelector('.template-select');
    const create = document.getElementById('new-template');
    if (selector && create) { toolbar.append(selector, create); form.prepend(toolbar); }
  }
  const sections = isWord
    ? [{ id: 'template-tools', label: 'Шаблон' }, { id: 'general-options', label: 'Общие' }, { id: 'format-options', label: 'MS Word' }]
    : [...form.querySelectorAll('.settings-section')].map((section, index) => {
        const id = ['ai-connection', 'ai-processing', 'ai-prompt'][index]; section.id = id;
        return { id, label: ['Подключение', 'Обработка', 'Промт'][index] };
      });
  if (!sections.length) return;
  const workspace = document.createElement('div'); workspace.className = 'settings-workspace';
  const spacer = document.createElement('div');
  spacer.className = 'settings-sidebar-space'; spacer.setAttribute('aria-hidden', 'true');
  form.before(workspace); workspace.append(spacer, form); document.body.classList.add('layout-enabled');
})();
