import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import './studio.css'
import './theme.css'
import './roles.css'
import './layout.css'
import './graph-layout.css'
import './chat-layout.css'
import './logo.css'
import './review-timeline.css'
import './grounding-references.css'

document.documentElement.dataset.theme = 'light'

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
