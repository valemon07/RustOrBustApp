/**
 * This file will automatically be loaded by vite and run in the "renderer" context.
*/
// Imports components
import React, { useState } from 'react';
import './index.css';
import './app.css';
import './themes.css';
import { createRoot } from 'react-dom/client';
import CenterPanel from './Components/CenterPanel';
import { ThemeProvider, ThemeSwitcherUI } from './Components/ThemeSwitcher';
import { SettingsProvider } from './contexts/SettingsContext';


// Defines the App component which will contain the rest of the components in the app.
const App = () => {
  const [showSettings, setShowSettings] = useState(false);

  return (
    <SettingsProvider>
      <ThemeProvider>
        <div className="app-shell">
          <main className={`main-stage ${showSettings ? 'settings-mode' : ''}`}>
            {!showSettings && (
              <header className="hero-copy">
                <p className="hero-kicker">Rust or Bust</p>
                <h1 className="hero-title">Fast Image Corrosion Quantification</h1>
                <p className="hero-subtitle">Upload images to run analysis and receive results</p>
              </header>
            )}
            <CenterPanel showSettings={showSettings} setShowSettings={setShowSettings} />
          </main>
          <ThemeSwitcherUI />
        </div>
      </ThemeProvider>
    </SettingsProvider>
  )
};

const root = createRoot(document.getElementById('root'));
root.render(<App/>);
