import '../../component/context_menu.js';

document.documentElement.classList.toggle('platform-macos', navigator.platform.startsWith('Mac'));

const statusEl = document.querySelector('#status');

async function applyLanguage() {
  let language = 'zh-CN';
  try {
    language = await window.__TAURI_INTERNALS__.invoke('interface_language');
  } catch {
    language = localStorage.getItem('calabash-language') || 'zh-CN';
  }
  document.documentElement.lang = language;
  statusEl.textContent = language === 'en' ? 'Starting local tools…' : '正在启动本地工具…';
  document.querySelector('.hint').textContent = language === 'en' ? 'Preparing your workspace' : '正在准备你的本地工具';
  document.querySelector('.loader').setAttribute('aria-label', language === 'en' ? 'Starting' : '正在启动');
}

applyLanguage();
