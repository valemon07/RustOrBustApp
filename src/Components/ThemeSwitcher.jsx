import React, { createContext, useContext, useState, useEffect } from 'react';
import './ThemeSwitcher.css';

const ThemeContext = createContext();

export const ThemeProvider = ({ children }) => {
  const [mode, setMode] = useState(localStorage.getItem('theme-mode') || 'light');

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', mode);
  }, [mode]);

  const setNewMode = (newMode) => {
    if (['light', 'dark', 'auto'].includes(newMode)) {
      setMode(newMode);
      localStorage.setItem('theme-mode', newMode);
    }
  };

  return (
    <ThemeContext.Provider value={{ mode, setNewMode }}>
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);

// UI Component: The floating theme menu for the bottom left
export function ThemeSwitcherUI() {
  const { mode, setNewMode } = useTheme();
  const [isOpen, setIsOpen] = React.useState(false);
  const menuRef = React.useRef(null);

  // Determine icon based on current mode
  const getIcon = () => {
    if (mode === 'light') return '☀️';
    if (mode === 'dark') return '🌙';
    // Auto: check system preference
    if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return '🌙';
    }
    return '☀️';
  };

  // Handle mode selection
  const handleSelectMode = (selectedMode) => {
    setNewMode(selectedMode);
    setIsOpen(false);
  };

  // Close menu when clicking outside
  React.useEffect(() => {
    const handleClickOutside = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  const modes = [
    { value: 'light', label: 'Light', icon: '☀️' },
    { value: 'dark', label: 'Dark', icon: '🌙' },
    { value: 'auto', label: 'Auto', icon: '✨' },
  ];

  const displayLabel = mode.charAt(0).toUpperCase() + mode.slice(1);

  return (
    <div className="theme-switcher-wrapper" ref={menuRef}>
      <button
        className="theme-switcher"
        onClick={() => setIsOpen(!isOpen)}
        aria-label={`Theme menu (current: ${mode})`}
        aria-expanded={isOpen}
        type="button"
      >
        <div className="theme-icon">
          {getIcon()}
        </div>
        <div className="mode-label">
          {displayLabel}
        </div>
      </button>

      <div className={`theme-menu ${isOpen ? 'open' : ''}`}>
        {modes.map((m) => (
          <button
            key={m.value}
            className={`theme-menu-item ${mode === m.value ? 'active' : ''}`}
            onClick={() => handleSelectMode(m.value)}
            type="button"
          >
            <span className="theme-menu-item-icon">{m.icon}</span>
            <span className="theme-menu-item-label">{m.label}</span>
            <span className="theme-menu-item-checkmark">✓</span>
          </button>
        ))}
      </div>
    </div>
  );
}