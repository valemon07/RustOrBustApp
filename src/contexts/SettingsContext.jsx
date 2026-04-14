import React, { createContext, useState } from 'react';

// Default settings 
const DEFAULT_SETTINGS = {
  largePixelAreaThreshold: 2000.0,
  scaleBreakpointHigh: 4.0,
  edgeReclassificationThreshold: 0.5,
  surfacePitDarknessThreshold: 0.3,
  customThresholds: [], // Array of floats sent to backend
};

export const SettingsContext = createContext();

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);
  const [useDefaults, setUseDefaults] = useState(true);

  const updateSetting = (key, value) => {
    setSettings(prev => ({
      ...prev,
      [key]: typeof value === 'string' ? parseFloat(value) || 0 : value
    }));
  };

  const resetToDefaults = () => {
    setSettings(DEFAULT_SETTINGS);
    setUseDefaults(true);
  };

  const exportSettings = () => {
    return useDefaults ? null : settings; // null signals: use backend defaults
  };

  return (
    <SettingsContext.Provider value={{
      settings,
      updateSetting,
      resetToDefaults,
      exportSettings,
      useDefaults,
      setUseDefaults
    }}>
      {children}
    </SettingsContext.Provider>
  );
}