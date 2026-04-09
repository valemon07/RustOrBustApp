/**
 * This file will automatically be loaded by vite and run in the "renderer" context.
*/
// Imports components
import React from 'react';
import './index.css';
import './app.css';
import './themes.css';
import { createRoot } from 'react-dom/client';
import CenterPanel from './Components/CenterPanel';
import { ThemeProvider, ThemeSwitcherUI } from './Components/ThemeSwitcher';


// Defines the App component which will contain the rest of the components in the app.
const App = () => {
  return (
    <ThemeProvider>
      <div className="app-shell">
        <main className="main-stage">
          <header className="hero-copy">
            <p className="hero-kicker">Rust or Bust</p>
            <h1 className="hero-title">Fast Image Corrosion Quantification</h1>
            <p className="hero-subtitle">Upload images to run analysis and receive results</p>
          </header>
          <CenterPanel />
        </main>
        <ThemeSwitcherUI />
      </div>
    </ThemeProvider>
  )
};

const root = createRoot(document.getElementById('root'));
root.render(<App/>);
