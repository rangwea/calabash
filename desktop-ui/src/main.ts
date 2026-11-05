import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import './workspace.css'
import '../../component/context_menu.js'

document.documentElement.classList.toggle('platform-macos', navigator.platform.startsWith('Mac'))
createApp(App).use(ElementPlus).mount('#app')
