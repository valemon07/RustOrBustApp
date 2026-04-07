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


// Defines the App component which will contain the rest of the components in the app.
const App = () => {
  return (
    <div className="app-shell">
      <main className="main-stage">
        <header className="hero-copy">
          <p className="hero-kicker">Rust or Bust</p>
          <h1 className="hero-title">Fast Rust Detection Starts Here</h1>
          <p className="hero-subtitle">Upload one or many images to run analysis and download a single combined CSV.</p>
        </header>
        <CenterPanel />
      </main>
    </div>
  )
};

const root = createRoot(document.getElementById('root'));
root.render(<App/>);
