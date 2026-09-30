import { StrictMode } from 'react'
import { BrowserRouter } from 'react-router-dom';
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { NuqsAdapter } from 'nuqs/adapters/react'
import type { OptimizeRequest, OptimizeResult } from './eink/optimize'

declare global {
  interface Window {
    optimizeWeatherScreenshot: (request: OptimizeRequest) => Promise<OptimizeResult>;
  }
}

// The library is loaded only when Playwright calls this bridge.
window.optimizeWeatherScreenshot = async request => {
  const { optimizeScreenshot } = await import('./eink/optimize');
  return optimizeScreenshot(request);
};

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <NuqsAdapter>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </NuqsAdapter>
  </StrictMode>,
)
