const navigationStyles = document.createElement('link'); navigationStyles.rel = 'stylesheet'; navigationStyles.href = '/app-nav.css'; document.head.append(navigationStyles);
async function setupAppNavigation() {
  const nav = document.querySelector('[data-app-nav], .app-nav, main > nav');
  if (!nav) return;
  const response = await fetch('/api/auth/me');
  const { user } = await response.json();
  if (!response.ok) return;
  const path = location.pathname;
  const maySettings = user.is_admin || user.can_access_settings;
  const mayFilters = user.is_admin || user.can_manage_filters;
  const settingsActive = path === '/settings.html' || path.startsWith('/openxml-');
  const icon = name => `<span class="menu-symbol" aria-hidden="true" style="--menu-symbol:url('/assets/icon-catalog/${name}.svg')"></span>`;
  const settingItems = `${maySettings ? `<a class="${path === '/settings.html' ? 'is-active' : ''}" href="/settings.html">${icon('bot')}Настройки ИИ</a>` : ''}${mayFilters ? `<a class="${path === '/openxml-word-options.html' ? 'is-active' : ''}" href="/openxml-word-options.html">${icon('file-sliders')}Настройки шаблона MS Word</a>` : ''}`;
  nav.className = 'app-nav unified-nav';
  nav.innerHTML = `<a class="app-brand" href="/"><img src="/assets/linguaflow-logo.svg" alt="LinguaFlow"></a><div class="app-links"><a class="${path === '/' ? 'is-active' : ''}" href="/">${icon('workflow')}Перевод</a><a class="${path === '/memories.html' ? 'is-active' : ''}" href="/memories.html">${icon('file-cog')}Память переводов</a>${settingItems ? `<div class="settings-menu"><button class="${settingsActive ? 'is-active' : ''}" type="button">${icon('settings')}Настройки</button><div class="settings-dropdown">${settingItems}</div></div>` : ''}${user.is_admin ? `<a class="${path === '/admin' ? 'is-active' : ''}" href="/admin">${icon('user-cog')}Администрирование</a>` : ''}</div><span class="account-name">${user.username}</span><button id="logout-button" type="button">${icon('log-out')}Выйти</button>`;
  document.getElementById('logout-button').onclick = async () => { await fetch('/api/auth/logout', {method:'POST'}); location.assign('/login'); };
}
setupAppNavigation();
