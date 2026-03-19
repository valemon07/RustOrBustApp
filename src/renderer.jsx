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
    <div>
      <h1>Welcome to Rust or Bust!</h1>
      <p>This is the beginning of the Rust or Bust app development.</p>
      <CenterPanel />
    </div>
  )
};

const root = createRoot(document.getElementById('root'));
root.render(<App/>);
